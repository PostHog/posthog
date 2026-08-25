"""Tests for the module selection behind the hog bytecode cache key.

Run with: uv run --with pytest pytest .github/scripts/test_hog_compiler_fingerprint.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from hog_compiler_fingerprint import select_paths

REPO = "/repo"
SELF = "/repo/.github/scripts/hog_compiler_fingerprint.py"


class TestSelectPaths:
    @pytest.mark.parametrize(
        "case,module_files,expected",
        [
            ("first party", ["/repo/posthog/hogql/ast.py"], ["posthog/hogql/ast.py"]),
            ("third party", ["/repo/.venv/lib/python3.13/site-packages/django/db.py"], []),
            ("outside the repo", ["/usr/lib/python3.13/os.py"], []),
            ("no file", [None], []),
            # A key that moves when this script gets a comment would invalidate every entry for
            # nothing, and multiprocessing re-registers the entry module, so excluding it by
            # module name misses the second copy.
            ("this script, once per module alias", [SELF, SELF], []),
        ],
    )
    def test_selects(self, case: str, module_files: list[str | None], expected: list[str]) -> None:
        assert select_paths(module_files, REPO, SELF) == expected, case

    def test_deduplicates_and_sorts(self) -> None:
        files = ["/repo/posthog/celery.py", "/repo/common/hogvm/python/operation.py", "/repo/posthog/celery.py"]

        assert select_paths(files, REPO, SELF) == ["common/hogvm/python/operation.py", "posthog/celery.py"]
