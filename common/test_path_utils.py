from __future__ import annotations

from pathlib import Path

import pytest

from common.path_utils import REPO_ROOT_MARKER, find_repo_root


def test_finds_marker_walking_up(tmp_path: Path) -> None:
    (tmp_path / REPO_ROOT_MARKER).write_text("")
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)

    assert find_repo_root(nested) == tmp_path


def test_accepts_file_path(tmp_path: Path) -> None:
    (tmp_path / REPO_ROOT_MARKER).write_text("")
    file_path = tmp_path / "a" / "b" / "module.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("")

    assert find_repo_root(file_path) == tmp_path


def test_raises_when_marker_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=REPO_ROOT_MARKER):
        find_repo_root(tmp_path)


def test_defaults_to_caller_file() -> None:
    # This test file lives inside the real repo, so the default lookup must
    # resolve to the actual checkout root.
    assert (find_repo_root() / REPO_ROOT_MARKER).is_file()


def test_returns_start_when_it_is_the_root(tmp_path: Path) -> None:
    (tmp_path / REPO_ROOT_MARKER).write_text("")

    assert find_repo_root(tmp_path) == tmp_path
