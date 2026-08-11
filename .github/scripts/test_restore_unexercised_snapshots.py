"""Tests for the snapshot-deletion guard in restore_unexercised_snapshots.

Run with: uv run --with pytest pytest .github/scripts/test_restore_unexercised_snapshots.py
"""

import pytest

from restore_unexercised_snapshots import repair, split_blocks

HEADER = "# serializer version: 1\n"


def block(name: str, body: str) -> str:
    return f"# name: {name}\n  '''\n  {body}\n  '''\n# ---\n"


LEGACY = block("TestQuery.test_one", "SELECT 1")
ALIAS = block("TestQuery.test_one[new_events_schema]", "SELECT 2 FROM events_json")
OTHER = block("TestQuery.test_two", "SELECT 3")


class TestRepair:
    def test_restores_block_the_run_deleted(self):
        head = HEADER + LEGACY + ALIAS + OTHER
        worktree = HEADER + LEGACY + OTHER

        result = repair(head, worktree)

        assert result is not None
        text, restored = result
        assert restored == ["TestQuery.test_one[new_events_schema]"]
        assert text == head

    def test_keeps_the_runs_updated_content_over_head(self):
        head = HEADER + LEGACY + ALIAS
        updated = block("TestQuery.test_one", "SELECT 1, 'new column'")
        worktree = HEADER + updated

        result = repair(head, worktree)

        assert result is not None
        text, _ = result
        assert text == HEADER + updated + ALIAS

    def test_restores_a_file_the_run_emptied(self):
        head = HEADER + LEGACY + ALIAS

        result = repair(head, "")

        assert result is not None
        text, restored = result
        assert len(restored) == 2
        assert text == head

    @pytest.mark.parametrize(
        "worktree",
        [
            pytest.param(HEADER + LEGACY + ALIAS, id="unchanged"),
            pytest.param(HEADER + LEGACY + ALIAS + OTHER, id="run-added-a-block"),
            pytest.param(HEADER + block("TestQuery.test_one", "SELECT 9") + ALIAS, id="run-updated-a-block"),
        ],
    )
    def test_no_rewrite_when_nothing_was_deleted(self, worktree):
        assert repair(HEADER + LEGACY + ALIAS, worktree) is None


class TestSplitBlocks:
    def test_multiline_body_containing_a_divider_like_line(self):
        # A snapshot body can contain "# ---" as indented data; only the unindented
        # marker ends a block, so a naive split would truncate the block here.
        tricky = "# name: TestQuery.test_one\n  '''\n  SELECT '# ---' AS x\n  '''\n# ---\n"

        header, blocks = split_blocks(HEADER + tricky)

        assert header == HEADER
        assert blocks == {"TestQuery.test_one": tricky}
