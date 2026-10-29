import sys
import subprocess
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).with_name("check-no-new-ee-files.py")
SPEC = importlib.util.spec_from_file_location("check_no_new_ee_files", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
check_no_new_ee_files = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_no_new_ee_files)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    (repo / "ee").mkdir(parents=True)
    (repo / "ee" / "kept.py").write_text("x = 1\n")
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    monkeypatch.chdir(repo)
    return repo


def _main(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["check-no-new-ee-files.py", "--against", "master", *args])
    return check_no_new_ee_files.main()


def test_committed_file_is_flagged(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "ee" / "new.py").write_text("y = 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add a file")

    assert _main(monkeypatch, "--committed") == 1
    assert "ee/new.py" in capsys.readouterr().out


def test_untracked_empty_file_is_flagged(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "ee" / "empty.py").touch()

    assert _main(monkeypatch) == 1
    assert "ee/empty.py" in capsys.readouterr().out


def test_edit_to_an_existing_file_passes(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / "ee" / "kept.py").write_text("x = 2\n")

    assert _main(monkeypatch) == 0


def test_exempt_path_passes(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / "ee" / "new.py").write_text("y = 2\n")
    monkeypatch.setattr(check_no_new_ee_files, "EXEMPT", frozenset({"ee/new.py"}))

    assert _main(monkeypatch) == 0
