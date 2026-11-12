import re
import sys
import tomllib
import subprocess
from pathlib import Path

BUILD_INPUTS = (
    "rust/",
    ".cargo/",
    ".github/actions/setup-uv/",
    ".github/workflows/ci-deltalite-python.yml",
    ".github/scripts/deltalite_selection.py",
    ".github/scripts/test_deltalite_selection.py",
    "Cargo.toml",
    "Cargo.lock",
    "rust-toolchain",
    "rust-toolchain.toml",
)
PIN_PREFIXES = ("deltalake[pyarrow]==", "pyarrow==", "duckdb~=")


def parity_config(source: str) -> dict[str, object]:
    config = tomllib.loads(source)
    dependencies = config["project"]["dependencies"]
    if not isinstance(dependencies, list) or not all(isinstance(dep, str) for dep in dependencies):
        raise ValueError("Invalid project dependencies")
    pins = []
    for prefix in PIN_PREFIXES:
        matches = [dep for dep in dependencies if dep.startswith(prefix)]
        installed = re.findall(r'"(' + re.escape(prefix) + r'[^"\n]*)"', source)
        if len(matches) != 1 or not installed or installed[0] != matches[0]:
            raise ValueError("Cannot identify an installed parity requirement")
        pins.extend(matches)
    config["project"]["dependencies"] = pins
    tool = config.get("tool")
    if isinstance(tool, dict):
        tool.pop("importlinter", None)
        if not tool:
            config.pop("tool")
    return config


def should_run(repo: Path, base: str, head: str = "HEAD") -> bool:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.PIPE)

    try:
        paths = git("diff", "--name-only", "--no-renames", "-z", base, head).split("\0")
        if any(path.startswith(BUILD_INPUTS) for path in paths if path):
            return True
        return parity_config(git("show", f"{base}:pyproject.toml")) != parity_config(
            git("show", f"{head}:pyproject.toml")
        )
    except (subprocess.CalledProcessError, ValueError, KeyError, TypeError):
        return True


if __name__ == "__main__":
    sys.stdout.write("true\n" if should_run(Path.cwd(), sys.argv[1]) else "false\n")
