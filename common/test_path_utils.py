from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from common.path_utils import REPO_ROOT_MARKER, find_repo_root


def _start_at_root(tmp_path: Path) -> Path:
    return tmp_path


def _start_in_nested_dir(tmp_path: Path) -> Path:
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    return nested


def _start_at_file(tmp_path: Path) -> Path:
    file_path = tmp_path / "a" / "b" / "module.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("")
    return file_path


@pytest.mark.parametrize(
    "make_start",
    [
        pytest.param(_start_at_root, id="start_is_root"),
        pytest.param(_start_in_nested_dir, id="nested_directory"),
        pytest.param(_start_at_file, id="file_path"),
    ],
)
def test_finds_root_from_various_start_types(
    tmp_path: Path, make_start: Callable[[Path], Path]
) -> None:
    (tmp_path / REPO_ROOT_MARKER).write_text("")
    assert find_repo_root(make_start(tmp_path)) == tmp_path


def test_raises_when_marker_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=REPO_ROOT_MARKER):
        find_repo_root(tmp_path)


def test_defaults_to_caller_file() -> None:
    # This test file lives inside the real repo, so the default lookup must
    # resolve to the actual checkout root.
    assert (find_repo_root() / REPO_ROOT_MARKER).is_file()
