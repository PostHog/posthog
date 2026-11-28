from datetime import datetime, timedelta

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql.scripts.multi_query_bench import run_batch
from posthog.hogql.scripts.multi_query_corpus import DEFAULT_WINDOW, build_corpus, synthetic_events

from posthog.models.event.util import bulk_create_events

BATCHES = {batch.name: batch for batch in build_corpus()}
NOW = datetime(DEFAULT_WINDOW.end.year, DEFAULT_WINDOW.end.month, DEFAULT_WINDOW.end.day) + timedelta(days=1)


class TestMultiQueryHarness(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            (name,)
            for name in (
                "daily_counts",
                "property_filter",
                "duplicate_tiles",
                "overlapping_windows",
                "mixed_dashboard",
                "table_alias",
                "daily_alias",
                "weekly_and_monthly",
                "mixed_spellings",
                "unsupported_buckets",
                "trends_series",
            )
        ]
    )
    def test_prepared_batch_shares_as_expected_and_matches_separate_results(self, name: str) -> None:
        batch = BATCHES[name]
        with time_machine.travel(NOW, tick=False):
            bulk_create_events(list(synthetic_events(self.team, DEFAULT_WINDOW, 600)))

            report = run_batch(batch, self.team)

        shared = {(group.rule, group.query_ids) for group in report.plan.groups if len(group.query_ids) > 1}
        self.assertEqual(shared, {(group.rule, group.query_ids) for group in batch.expected_groups})
        rejections = {(r.query_id, r.rule, r.reason, False) for r in report.plan.rejections} | {
            (r.query_id, r.rule, r.reason, True) for r in report.lifted_rejections
        }
        for expected in batch.expected_rejections:
            self.assertIn((expected.query_id, expected.rule, expected.reason, expected.limit_lifted), rejections)
        self.assertEqual(report.mismatches, ())
        self.assertTrue(all(result.rows for result in report.results.values()), report.results)
        self.assertEqual(
            (report.separate.executions, report.combined.executions), (report.query_count, len(report.plan.groups))
        )
