import subprocess
from pathlib import Path

import pytest

from deltalite_selection import should_run

PROJECT = """[project]
name = "example"
dependencies = ["deltalake[pyarrow]==1.0.0", "pyarrow==23.0.0", "duckdb~=1.5.0", "example==1.0.0"]
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.PIPE).strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "pyproject.toml").write_text(PROJECT)
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    return tmp_path


@pytest.mark.parametrize(
    "path,content,expected",
    [
        ("uv.lock", "changed", False),
        ("pyproject.toml", PROJECT.replace("example==1.0.0", "example==2.0.0"), False),
        ("pyproject.toml", PROJECT.replace("deltalake[pyarrow]==1.0.0", "deltalake[pyarrow]==2.0.0"), True),
        ("pyproject.toml", PROJECT.replace("pyarrow==23.0.0", "pyarrow==24.0.0"), True),
        ("pyproject.toml", PROJECT.replace("duckdb~=1.5.0", "duckdb~=1.6.0"), True),
        ("pyproject.toml", PROJECT.replace("pyarrow==23.0.0", "pyarrow>=23.0.0"), True),
        ("pyproject.toml", "invalid toml", True),
        ("pyproject.toml", PROJECT + '\n[build-system]\nrequires = ["example"]\n', True),
        ("rust/Cargo.lock", "changed", True),
        ("rust/deltalite/src/lib.rs", "changed", True),
        (".cargo/config.toml", "changed", True),
        (".github/actions/setup-uv/action.yml", "changed", True),
        (".github/workflows/ci-deltalite-python.yml", "changed", True),
    ],
)
def test_changed_inputs(repo: Path, path: str, content: str, expected: bool) -> None:
    changed = repo / path
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text(content)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "change")
    assert should_run(repo, "HEAD^1") is expected


def test_missing_base_runs_suite(repo: Path) -> None:
    assert should_run(repo, "HEAD^1") is True


def test_renamed_input_runs_suite(repo: Path) -> None:
    git(repo, "mv", "pyproject.toml", "renamed.toml")
    git(repo, "commit", "-qm", "rename")
    assert should_run(repo, "HEAD^1") is True


def test_large_diff_keeps_build_input(repo: Path) -> None:
    for index in range(310):
        (repo / f"example-{index}.txt").write_text("example")
    (repo / "rust").mkdir()
    (repo / "rust/Cargo.lock").write_text("changed")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "large change")
    assert should_run(repo, "HEAD^1") is True
