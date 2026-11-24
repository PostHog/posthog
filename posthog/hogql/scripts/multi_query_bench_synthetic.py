"""Synthetic data source for `multi_query_bench --synthetic`.

pytest provides the test databases, so this module holds the benchmark as a test case. Its file name keeps it out of
normal collection; it runs only when its node ID is passed to pytest explicitly.
"""

import os
from itertools import islice

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.hogql.scripts.multi_query_bench import (
    SYNTHETIC_BATCHES_VARIABLE,
    SYNTHETIC_ROWS_VARIABLE,
    format_reports,
    run_corpus,
)
from posthog.hogql.scripts.multi_query_corpus import DEFAULT_WINDOW, synthetic_events

from posthog.clickhouse.client import sync_execute
from posthog.models.event.util import bulk_create_events

_CHUNK = 5_000


class SyntheticBenchmark(ClickhouseTestMixin, BaseTest):
    def test_report(self) -> None:
        rows = int(os.environ.get(SYNTHETIC_ROWS_VARIABLE, "60000"))
        batches = [name for name in os.environ.get(SYNTHETIC_BATCHES_VARIABLE, "").split(",") if name]
        events = synthetic_events(self.team, DEFAULT_WINDOW, rows)
        while chunk := list(islice(events, _CHUNK)):
            bulk_create_events(chunk)
        seeded = sync_execute("SELECT count() FROM events WHERE team_id = %(team_id)s", {"team_id": self.team.pk})[0][0]
        print(  # noqa: T201
            f"\nSynthetic: {seeded:,} events for one project over {DEFAULT_WINDOW.days} days from "
            f"{DEFAULT_WINDOW.start}, in the pytest test databases.\n"
        )
        reports = run_corpus(self.team, batches=batches)
        print(format_reports(reports))  # noqa: T201
        print(  # noqa: T201
            "\nRows read and ClickHouse time come from the server. Wall time includes HogQL compilation."
            "\nSeparate runs go first, so the combined run can find warmer caches."
        )
        self.assertEqual([report.name for report in reports if report.mismatches], [])
