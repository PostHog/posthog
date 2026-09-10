from datetime import date

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.query_scan.analyze import analyze_settings
from posthog.query_scan.explain import QueryPlan, parse_query_plan
from posthog.query_scan.findings import (
    FindingKind,
    FindingReason,
    ScanMeasurements,
    ScanThresholds,
    build_warning,
    explain_evidence,
    format_rows,
    passes_event_gate,
    passes_persons_gate,
)
from posthog.query_scan.test.test_explain import MIXED_PRUNING_PLAN, load_plan, plan_read

THRESHOLDS = ScanThresholds()


def unnamed_key_read() -> dict[str, object]:
    return {
        "Node Type": "ReadFromMergeTree",
        "Description": "posthog.sharded_events",
        "Indexes": [{"Type": "PrimaryKey"}],
    }


class TestFindings(SimpleTestCase):
    @parameterized.expand([("8.4 billion", 8_400_000_000), ("12,345", 12_345)])
    def test_row_counts_read_as_words_above_a_million(self, expected: str, rows: int) -> None:
        self.assertEqual(format_rows(rows), expected)

    @parameterized.expand(
        [
            ("exactly at the ratio", 100, None, 1000, True),
            ("below the ratio: something else pruned the read", 99, None, 1000, False),
            ("no count available", 3_000_000_000, None, None, False),
            ("the events side alone is below the ratio", 3_000_000_000, 99, 1000, False),
        ]
    )
    def test_event_gate(
        self,
        _name: str,
        rows_read: int,
        events_rows_read: int | None,
        events_in_range: int | None,
        expected: bool,
    ) -> None:
        measurements = ScanMeasurements(
            rows_read=rows_read,
            duration_ms=6000,
            events_in_range=events_in_range,
            events_rows_read=events_rows_read,
        )

        self.assertEqual(passes_event_gate(measurements, THRESHOLDS), expected)

    @parameterized.expand(
        [
            ("persons dominate the read", 3_000_000, 150_000_000, True),
            ("persons are a rounding error", 3_000_000_000, 1_000, False),
            ("no person count available", 3_000_000, None, False),
        ]
    )
    def test_persons_gate(self, _name: str, rows_read: int, person_rows: int | None, expected: bool) -> None:
        measurements = ScanMeasurements(rows_read=rows_read, duration_ms=3000, person_rows=person_rows)

        self.assertEqual(passes_persons_gate(measurements, THRESHOLDS), expected)

    @parameterized.expand(
        [
            (
                "the read that could not prune on event",
                MIXED_PRUNING_PLAN,
                "ClickHouse used the primary key columns team_id, toDate(timestamp) and kept "
                "40,000 of 60,000 granules.",
            ),
            (
                "the only read, when every read pruned",
                parse_query_plan(load_plan("event_filter_usable")),
                "ClickHouse used the primary key columns team_id, toDate(timestamp), event and kept "
                "800 of 60,000 granules.",
            ),
            (
                "a read that names no key columns, beside one that does",
                parse_query_plan(
                    [{"Plan": unnamed_key_read()}, {"Plan": plan_read(["team_id", "toDate(timestamp)"], 40000)}]
                ),
                "ClickHouse used the primary key columns team_id, toDate(timestamp) and kept "
                "40,000 of 60,000 granules.",
            ),
            ("no read names any key columns", parse_query_plan([{"Plan": unnamed_key_read()}]), None),
        ]
    )
    def test_evidence_names_the_read_the_finding_is_about(
        self, _name: str, plan: QueryPlan, expected: str | None
    ) -> None:
        self.assertEqual(explain_evidence(plan), expected)

    @parameterized.expand(
        [
            (
                FindingKind.NO_EVENT_FILTER,
                None,
                None,
                (
                    "Queries are fastest when they name a fixed set of events. This query has no event filter, so it "
                    "reads every event you have ever sent, which is slow. If the question is about specific events, "
                    "add `WHERE event IN ('…')` naming them."
                ),
            ),
            (
                FindingKind.EVENT_FILTER_NOT_USED,
                FindingReason.IN_OR,
                "properties.plan = 'pro' OR event = 'upgrade'",
                (
                    "Queries are fastest when they name a fixed set of events. This query names events only inside an "
                    "OR with another condition (`properties.plan = 'pro' OR event = 'upgrade'`), so that filter cannot "
                    "be used and it still reads every event, which is slow. Put the event filter outside the OR: "
                    "`WHERE event IN ('…') AND (… OR …)`."
                ),
            ),
        ]
    )
    def test_message_pairs_the_lead_with_its_advice_and_quotes_the_clause(
        self, kind: FindingKind, reason: FindingReason | None, clause: str | None, expected: str
    ) -> None:
        warning = build_warning(
            kind=kind,
            reason=reason,
            clause=clause,
            measurements=ScanMeasurements(rows_read=8_400_000_000, duration_ms=19_000, person_rows=150_000_000),
        )

        self.assertEqual(warning.type, "query_scan")
        self.assertEqual(warning.message, expected)
        self.assertEqual(warning.clause, clause)
        self.assertEqual(warning.rows_read, 8_400_000_000)


class TestSettingsAnalysis(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "all events under the ratio",
                {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": None}]},
                1_000,
                1_000_000_000,
                [],
            ),
            (
                "a named event",
                {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
                700_000_000,
                1_000_000_000,
                [],
            ),
            (
                "all time, with no event count to gate on",
                {"kind": "TrendsQuery", "series": [], "dateRange": {"date_from": "all"}},
                40_000_000_000,
                None,
                ["all_time"],
            ),
            (
                "all events and all time",
                {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": None}],
                    "dateRange": {"date_from": "all"},
                },
                40_000_000_000,
                40_000_000_000,
                ["all_events", "all_time"],
            ),
            (
                "retention is out of scope in v1",
                {
                    "kind": "RetentionQuery",
                    "series": [{"kind": "EventsNode", "event": None}],
                    "dateRange": {"date_from": "all"},
                },
                40_000_000_000,
                40_000_000_000,
                [],
            ),
        ]
    )
    def test_findings_for_picker_built_insights(
        self,
        _name: str,
        query: dict[str, object],
        rows_read: int,
        events_in_range: int | None,
        expected_kinds: list[str],
    ) -> None:
        result = analyze_settings(
            query,
            date_from=date(2026, 3, 1),
            date_to=date(2026, 3, 8),
            rows_read=rows_read,
            duration_ms=4000,
            events_in_range=events_in_range,
            thresholds=THRESHOLDS,
        )

        self.assertEqual(result.finding_kinds(), expected_kinds)
