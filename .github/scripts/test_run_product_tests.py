import os
import sys
import shutil
import subprocess
from pathlib import Path

import pytest

RUNNER = Path(__file__).parent / "run-product-tests.sh"

# The .github/scripts CI job has no pytest-split, so the fake repo accepts its flags itself.
# Where pytest-split is installed, the plugin owns the flags and addoption raises ValueError.
SPLIT_OPTIONS_CONFTEST = """
def pytest_addoption(parser):
    try:
        parser.addoption("--splits")
        parser.addoption("--group")
    except ValueError:
        pass
"""


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    scripts = tmp_path / ".github" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(RUNNER, scripts / RUNNER.name)
    (scripts / "product-tests-owned-elsewhere.txt").write_text(
        "# owned by other jobs\n\nproducts/*/dags \r\nproducts/foo/vendor"
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "conftest.py").write_text(SPLIT_OPTIONS_CONFTEST)
    for test_file in ("backend/tests/test_a.py", "scripts/test_b.py", "dags/test_c.py", "vendor/test_d.py"):
        path = tmp_path / "products" / "foo" / test_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_it():\n    pass\n")
    (tmp_path / "products" / "empty").mkdir()
    return tmp_path


@pytest.mark.parametrize(
    "product,split_args,expected_returncode,expected_ids",
    [
        ("foo", [], 0, ["products/foo/backend/tests/test_a.py::test_it", "products/foo/scripts/test_b.py::test_it"]),
        ("empty", [], 5, []),
        ("empty", ["--splits", "2", "--group", "1"], 0, []),
    ],
)
def test_runner_collects_every_test_outside_the_owned_paths(
    fake_repo: Path, product: str, split_args: list[str], expected_returncode: int, expected_ids: list[str]
) -> None:
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        ["bash", str(fake_repo / ".github" / "scripts" / RUNNER.name), product, *split_args, "--collect-only", "-qq"],
        cwd=fake_repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == expected_returncode, result.stdout + result.stderr
    collected = sorted(line for line in result.stdout.splitlines() if "::" in line)
    assert collected == expected_ids
