import os
import tempfile
from datetime import UTC, datetime
from io import StringIO

from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

from posthog.management.commands.compare_retention_correctness import (
    Command,
    ProgressState,
    Row,
    _check_one,
    format_cell_sample,
    journal_line,
    merge_progress_state,
    parse_journal_lines,
    revalidate_mismatches,
    scope_signature,
    unabsorbed_journal_rows,
)
from posthog.management.commands.compare_retention_legacy_vs_dwh import CellDiff
from posthog.management.commands.test.test_compare_retention_legacy_vs_dwh import FakeObjectStorage
from posthog.models import Team

from products.product_analytics.backend.models.insight import Insight


def _row(insight_id, status, detail=""):
    return Row(
        id=insight_id, short_id=f"s{insight_id}", team_id=1, url=f"url{insight_id}", status=status, detail=detail
    )


class TestMergeProgressState(TestCase):
    def test_accumulates_counts_and_findings_across_batches(self):
        first = merge_progress_state(
            None, [_row(1, "OK"), _row(2, "MISMATCH", "d2")], next_cursor=2, complete=False, scope="S"
        )
        second = merge_progress_state(
            first,
            [_row(3, "ERROR", "e3"), _row(4, "OK"), _row(5, "ERROR_DWH", "e5")],
            next_cursor=5,
            complete=False,
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
        first = merge_progress_state(None, [_row(1, "MISMATCH")], next_cursor=1, complete=False, scope="S")
        merge_progress_state(first, [_row(2, "MISMATCH")], next_cursor=2, complete=False, scope="S")
        self.assertEqual(first.processed, 1)
        self.assertEqual(len(first.mismatches), 1)

    def test_cursor_never_regresses(self):
        first = merge_progress_state(None, [_row(5, "OK")], next_cursor=5, complete=False, scope="S")
        rewound = merge_progress_state(first, [_row(2, "OK")], next_cursor=2, complete=False, scope="S")
        self.assertEqual(rewound.cursor, 5)

    def test_empty_batch_leaves_cursor_in_place(self):
        first = merge_progress_state(None, [_row(1, "OK"), _row(2, "OK")], next_cursor=2, complete=False, scope="S")
        self.assertFalse(first.complete)
        done = merge_progress_state(first, [], next_cursor=None, complete=True, scope="S")
        self.assertTrue(done.complete)
        self.assertEqual(done.cursor, 2)
        self.assertEqual(done.processed, 2)

    def test_start_of_run_claim_folds_like_no_checkpoint(self):
        # The claim written at run start must stay a neutral element: if it ever carried counts
        # or a cursor, a resumed sweep would double-count (or drop) the journal-recovered rows.
        claim = ProgressState(scope="S", writer="pod-a", updated_at="2026-08-04T00:00:00+00:00")
        rows = [_row(1, "OK"), _row(2, "MISMATCH", "d2")]
        self.assertEqual(
            merge_progress_state(claim, rows, next_cursor=2, complete=True, scope="S"),
            merge_progress_state(None, rows, next_cursor=2, complete=True, scope="S"),
        )


class TestJournal(TestCase):
    def test_recovers_rows_dropping_a_line_torn_by_the_interrupt(self):
        rows = [_row(1, "OK"), _row(2, "MISMATCH", "2 stable cell diff(s)")]
        lines = ['{"scope": "S"}', *(journal_line(r) for r in rows), '{"id": 3, "short_id": "s3", "tea']
        self.assertEqual(parse_journal_lines(lines, "S"), rows)

    def test_refuses_journal_from_a_different_filter_set(self):
        lines = ['{"scope": "S"}', journal_line(_row(1, "OK"))]
        with self.assertRaises(ValueError):
            parse_journal_lines(lines, "OTHER")

    def test_append_after_torn_tail_starts_on_a_fresh_line(self):
        # A plain append would glue the resumed run's first record onto the torn fragment,
        # silently losing both rows on the next recovery.
        cmd = Command(stdout=StringIO())
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sweep.json.journal")
            sink = cmd._open_journal(path, scope="S", recovered=[])
            assert sink is not None
            sink.append(journal_line(_row(1, "OK")))
            sink.close()
            with open(path, "a") as handle:
                handle.write('{"id": 2, "sho')  # the interrupt tears a write mid-line
            sink = cmd._open_journal(path, scope="S", recovered=[])
            assert sink is not None
            sink.append(journal_line(_row(2, "OK")))
            sink.close()
            recovered = cmd._load_journal(path, scope="S", restart=False)
            self.assertEqual([r.id for r in recovered], [1, 2])

    def test_remote_journal_reseeds_recovered_rows_on_resume(self):
        # Each object-storage upload replaces the whole journal, so a resumed run that fails to
        # seed the recovered rows erases them with its first upload.
        cmd = Command(stdout=StringIO())
        path = "s3://retention/sweep.json.journal"
        fake = FakeObjectStorage()
        with patch("posthog.management.commands.compare_retention_legacy_vs_dwh.object_storage", fake):
            sink = cmd._open_journal(path, scope="S", recovered=[])
            assert sink is not None
            sink.append(journal_line(_row(1, "OK")))
            sink.close()  # stands in for the SIGTERM flush of an evicted pod
            recovered = cmd._load_journal(path, scope="S", restart=False)
            self.assertEqual([r.id for r in recovered], [1])
            sink = cmd._open_journal(path, scope="S", recovered=recovered)
            assert sink is not None
            sink.append(journal_line(_row(2, "OK")))
            sink.close()
            self.assertEqual([r.id for r in cmd._load_journal(path, scope="S", restart=False)], [1, 2])


class TestUnabsorbedJournalRows(TestCase):
    def test_rows_already_folded_into_the_checkpoint_are_dropped(self):
        # A journal outlives its absorb only when the post-save delete failed; folding those
        # rows again would double-count every one of them.
        rows = [_row(5, "OK"), _row(10, "OK"), _row(15, "OK")]
        self.assertEqual([r.id for r in unabsorbed_journal_rows(rows, 10)], [15])

    def test_without_a_checkpoint_every_row_is_pending(self):
        rows = [_row(5, "OK")]
        self.assertEqual(unabsorbed_journal_rows(rows, None), rows)

    def test_start_of_run_claim_absorbs_nothing(self):
        # The claim's cursor is 0: were it ever written with a real cursor (say --after-id),
        # journal rows at or below it would be treated as absorbed and their results dropped.
        rows = [_row(1, "OK"), _row(7, "OK")]
        self.assertEqual(unabsorbed_journal_rows(rows, 0), rows)


class TestProgressStateRoundTrip(TestCase):
    def test_to_dict_from_dict_preserves_state(self):
        state = merge_progress_state(
            None, [_row(1, "OK"), _row(2, "MISMATCH", "d")], next_cursor=2, complete=False, scope="SC"
        )
        state.writer = "pod-a"
        state.updated_at = "2026-08-03T00:00:00+00:00"
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


class TestFormatCellSample(TestCase):
    # Cell dumps steer prod triage; printing dwh where legacy belongs would invert every
    # conclusion, and a dropped overflow marker would pass off a sample as the full diff.
    def test_order_prefix_and_overflow(self):
        cells = [
            CellDiff(
                breakdown_value=None,
                row_label="Day 2",
                value_label="Day 1-5",
                field="count",
                legacy=12.0,
                dwh=11.0,
                abs_diff=1.0,
                rel_diff=None,
            ),
            CellDiff(
                breakdown_value="Chrome",
                row_label="Day 0",
                value_label="Day 0",
                field="aggregation_value",
                legacy=3.5,
                dwh=4.0,
                abs_diff=0.5,
                rel_diff=None,
            ),
            CellDiff(
                breakdown_value=None,
                row_label="Day 3",
                value_label="Day 6-10",
                field="count",
                legacy=2.0,
                dwh=0.0,
                abs_diff=2.0,
                rel_diff=None,
            ),
        ]
        self.assertEqual(
            format_cell_sample(cells, 2),
            "Day 2/Day 1-5 12≠11; [Chrome] Day 0/Day 0 agg 3.5≠4 (+1 more)",
        )


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
