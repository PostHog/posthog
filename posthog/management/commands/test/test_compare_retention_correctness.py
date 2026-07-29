from datetime import UTC, datetime

from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

from posthog.management.commands.compare_retention_correctness import (
    ProgressState,
    Row,
    _check_one,
    merge_progress_state,
    revalidate_mismatches,
    scope_signature,
)
from posthog.models import Team

from products.product_analytics.backend.models.insight import Insight


def _row(insight_id, status, detail=""):
    return Row(
        id=insight_id, short_id=f"s{insight_id}", team_id=1, url=f"url{insight_id}", status=status, detail=detail
    )


class TestMergeProgressState(TestCase):
    def test_accumulates_counts_and_findings_across_batches(self):
        first = merge_progress_state(
            None, [_row(1, "OK"), _row(2, "MISMATCH", "d2")], next_cursor=2, limit=2, scope="S"
        )
        second = merge_progress_state(
            first,
            [_row(3, "ERROR", "e3"), _row(4, "OK"), _row(5, "ERROR_DWH", "e5")],
            next_cursor=5,
            limit=3,
            scope="S",
        )
        self.assertEqual(second.processed, 5)
        self.assertEqual(second.counts["OK"], 2)
        self.assertEqual(second.counts["MISMATCH"], 1)
        self.assertEqual(second.counts["ERROR"], 1)
        self.assertEqual(second.counts["ERROR_DWH"], 1)
        self.assertEqual([m["id"] for m in second.mismatches], [2])
        # Attributed errors accumulate alongside plain ones, keeping their status in the record.
        self.assertEqual([(e["id"], e["status"]) for e in second.errors], [(3, "ERROR"), (5, "ERROR_DWH")])
        self.assertEqual(second.cursor, 5)

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
        # A state file written before the attributed ERROR_* statuses or resolved_mismatches
        # existed must still load.
        restored = ProgressState.from_dict({"cursor": 7, "counts": {"OK": 3, "ERROR": 1}})
        self.assertEqual(restored.cursor, 7)
        self.assertEqual(restored.counts["OK"], 3)
        self.assertEqual(restored.counts["ERROR"], 1)
        self.assertEqual(restored.counts["ERROR_DWH"], 0)
        self.assertEqual(restored.mismatches, [])
        self.assertEqual(restored.resolved_mismatches, [])
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

    def test_distinguishes_recheck_mismatches(self):
        # Stability-filtered and raw MISMATCH verdicts must not accumulate into one sweep.
        self.assertNotEqual(
            scope_signature({"recheck_mismatches": True}), scope_signature({"recheck_mismatches": False})
        )


def _mismatch_record(insight_id):
    return {
        "id": insight_id,
        "short_id": f"s{insight_id}",
        "team_id": 1,
        "url": f"url{insight_id}",
        "status": "MISMATCH",
        "detail": "2 stable cell diff(s)",
    }


class TestRevalidateMismatches(TestCase):
    @parameterized.expand(
        [
            ("recheck_ok", _row(1, "OK"), "OK"),
            ("references_now_deleted", _row(1, "SKIPPED", "action deleted"), "SKIPPED"),
            ("insight_gone", None, "SKIPPED"),
        ]
    )
    def test_resolves_when_no_longer_reproducing(self, _name, recheck_row, resolved_status):
        counts = {"MISMATCH": 1, "OK": 5, "SKIPPED": 0}
        kept, resolved, new_counts = revalidate_mismatches([_mismatch_record(1)], counts, lambda rec: recheck_row)
        self.assertEqual(kept, [])
        self.assertEqual(len(resolved), 1)
        self.assertIn("resolution", resolved[0])
        self.assertEqual(new_counts["MISMATCH"], 0)
        self.assertEqual(new_counts[resolved_status], counts[resolved_status] + 1)
        # Inputs stay untouched so a crash between revalidation and save can't lose findings.
        self.assertEqual(counts["MISMATCH"], 1)

    def test_keeps_and_refreshes_still_reproducing_mismatch(self):
        kept, resolved, new_counts = revalidate_mismatches(
            [_mismatch_record(1)],
            {"MISMATCH": 1},
            lambda rec: _row(1, "MISMATCH", "1 stable cell diff(s), values moved (churn)"),
        )
        self.assertEqual(resolved, [])
        self.assertEqual(new_counts["MISMATCH"], 1)
        self.assertEqual(kept[0]["detail"], "1 stable cell diff(s), values moved (churn)")

    def test_errored_recheck_keeps_record_untouched(self):
        record = _mismatch_record(1)
        kept, resolved, new_counts = revalidate_mismatches([record], {"MISMATCH": 1}, lambda rec: _row(1, "ERROR_DWH"))
        self.assertEqual(kept, [record])
        self.assertEqual(resolved, [])
        self.assertEqual(new_counts["MISMATCH"], 1)


def _retention_insight():
    # Unsaved team; personsOnEventsMode pinned so modifier defaulting needs no DB or flag lookups.
    team = Team(pk=1, timezone="UTC", modifiers={"personsOnEventsMode": "person_id_no_override_properties_on_events"})
    return Insight(
        id=42,
        short_id="abc123",
        team=team,
        query={
            "kind": "InsightVizNode",
            "source": {
                "kind": "RetentionQuery",
                "dateRange": {"date_to": "2023-04-10T00:00:00.000Z", "explicitDate": False},
                "retentionFilter": {
                    "period": "Day",
                    "targetEntity": {"id": "start", "type": "events"},
                    "returningEntity": {"id": "start", "type": "events"},
                    "retentionType": "retention_first_time",
                    "totalIntervals": 3,
                },
            },
        },
    )


def _retention_results(day0_count):
    return [
        {
            "breakdown_value": None,
            "label": "Day 0",
            "date": datetime(2023, 4, 8, tzinfo=UTC),
            "values": [{"count": day0_count, "label": "Day 0"}, {"count": 1, "label": "Day 1"}],
        }
    ]


class TestRecheckStabilityClassification(TestCase):
    def _check_with_fake_variants(self, fake):
        with patch("posthog.management.commands.compare_retention_correctness._try_variant", side_effect=fake):
            return _check_one(_retention_insight(), "url", freeze=False, recheck=True)

    def test_replica_alternation_is_classified_as_churn_not_deterministic(self):
        # Divergent replica part-sets serve different data per QUERY, regardless of variant. A strict
        # legacy→dwh→legacy→dwh cadence phase-locks each variant onto one state, which used to read
        # as a value-identical "deterministic" difference. The reversed recheck order must classify
        # this as churn.
        states = [_retention_results(16), _retention_results(15)]
        calls = {"n": 0}

        def alternating_replicas(insight, use_dwh, modifiers, override):
            result = states[calls["n"] % 2]
            calls["n"] += 1
            return result, None

        row = self._check_with_fake_variants(alternating_replicas)
        self.assertEqual(row.status, "MISMATCH")
        self.assertIn("values moved between passes (churn", row.detail)
        self.assertNotIn("value-identical", row.detail)

    def test_true_variant_difference_stays_deterministic(self):
        def variant_dependent(insight, use_dwh, modifiers, override):
            return _retention_results(15 if use_dwh else 16), None

        row = self._check_with_fake_variants(variant_dependent)
        self.assertEqual(row.status, "MISMATCH")
        self.assertIn("value-identical (deterministic)", row.detail)
