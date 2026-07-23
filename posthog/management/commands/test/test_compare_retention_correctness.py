from unittest import TestCase

from parameterized import parameterized

from posthog.management.commands.compare_retention_correctness import (
    ProgressState,
    Row,
    merge_progress_state,
    scope_signature,
)


def _row(insight_id, status, detail=""):
    return Row(
        id=insight_id, short_id=f"s{insight_id}", team_id=1, url=f"url{insight_id}", status=status, detail=detail
    )


class TestMergeProgressState(TestCase):
    def test_accumulates_counts_and_findings_across_batches(self):
        first = merge_progress_state(
            None, [_row(1, "OK"), _row(2, "MISMATCH", "d2")], next_cursor=2, limit=2, scope="S"
        )
        second = merge_progress_state(first, [_row(3, "ERROR", "e3"), _row(4, "OK")], next_cursor=4, limit=2, scope="S")
        self.assertEqual(second.processed, 4)
        self.assertEqual(second.counts, {"OK": 2, "MISMATCH": 1, "ERROR": 1, "SKIPPED": 0})
        self.assertEqual([m["id"] for m in second.mismatches], [2])
        self.assertEqual([e["id"] for e in second.errors], [3])
        self.assertEqual(second.cursor, 4)

    def test_does_not_mutate_previous_state(self):
        first = merge_progress_state(None, [_row(1, "MISMATCH")], next_cursor=1, limit=10, scope="S")
        merge_progress_state(first, [_row(2, "MISMATCH")], next_cursor=2, limit=10, scope="S")
        self.assertEqual(first.processed, 1)
        self.assertEqual(len(first.mismatches), 1)

    def test_cursor_never_regresses(self):
        first = merge_progress_state(None, [_row(5, "OK")], next_cursor=5, limit=1, scope="S")
        rewound = merge_progress_state(first, [_row(2, "OK")], next_cursor=2, limit=10, scope="S")
        self.assertEqual(rewound.cursor, 5)


class TestSweepCompletion(TestCase):
    @parameterized.expand(
        [
            ("full_batch_keeps_going", 3, 3, False),
            ("short_batch_completes", 2, 3, True),
            ("empty_batch_completes", 0, 3, True),
        ]
    )
    def test_complete_iff_batch_smaller_than_limit(self, _name, batch_size, limit, expected):
        rows = [_row(i, "OK") for i in range(1, batch_size + 1)]
        state = merge_progress_state(None, rows, next_cursor=batch_size or None, limit=limit, scope="S")
        self.assertEqual(state.complete, expected)

    def test_empty_batch_leaves_cursor_in_place(self):
        first = merge_progress_state(None, [_row(1, "OK"), _row(2, "OK")], next_cursor=2, limit=2, scope="S")
        self.assertFalse(first.complete)
        done = merge_progress_state(first, [], next_cursor=None, limit=2, scope="S")
        self.assertTrue(done.complete)
        self.assertEqual(done.cursor, 2)
        self.assertEqual(done.processed, 2)


class TestProgressStateRoundTrip(TestCase):
    def test_to_dict_from_dict_preserves_state(self):
        state = merge_progress_state(
            None, [_row(1, "OK"), _row(2, "MISMATCH", "d")], next_cursor=2, limit=2, scope="SC"
        )
        self.assertEqual(ProgressState.from_dict(state.to_dict()), state)

    def test_from_dict_tolerates_missing_keys(self):
        restored = ProgressState.from_dict({"cursor": 7})
        self.assertEqual(restored.cursor, 7)
        self.assertEqual(restored.counts, {"OK": 0, "MISMATCH": 0, "ERROR": 0, "SKIPPED": 0})
        self.assertEqual(restored.mismatches, [])
        self.assertFalse(restored.complete)


class TestScopeSignature(TestCase):
    def test_order_insensitive_and_defaults_for_missing_keys(self):
        explicit = scope_signature(
            {"team_id": [2, 1], "insight_id": [], "short_id": ["b", "a"], "freeze_window": False}
        )
        reordered = scope_signature({"team_id": [1, 2], "short_id": ["a", "b"]})
        self.assertEqual(explicit, reordered)

    def test_distinguishes_freeze_window(self):
        self.assertNotEqual(scope_signature({"freeze_window": True}), scope_signature({"freeze_window": False}))

    def test_distinguishes_team_filter(self):
        self.assertNotEqual(scope_signature({"team_id": [1]}), scope_signature({"team_id": [2]}))
