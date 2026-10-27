"""The `ee/` new-file guard, which CI and `hogli ci:preflight` both call.

A path comparison, not a content scan: the zero-byte case is the one a content scan misses.
"""

import sys
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[3] / ".github" / "scripts" / "check-no-new-ee-files.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
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
    return repo


def _check(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--against", "master", *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def test_committed_file_is_flagged(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "ee" / "new.py").write_text("y = 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add a file")

    result = _check(repo, "--committed")

    assert result.returncode == 1
    assert "ee/new.py" in result.stdout


def test_untracked_empty_file_is_flagged(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "ee" / "empty.py").touch()

    result = _check(repo)

    assert result.returncode == 1
    assert "ee/empty.py" in result.stdout


def test_edit_to_an_existing_file_passes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "ee" / "kept.py").write_text("x = 2\n")

    assert _check(repo).returncode == 0
