from datetime import date

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.query_scan.analyze import analyze_settings
from posthog.query_scan.findings import (
    FindingKind,
    FindingReason,
    ScanMeasurements,
    ScanThresholds,
    build_warning,
    format_rows,
    passes_event_gate,
    passes_persons_gate,
)

THRESHOLDS = ScanThresholds()


class TestFindings(SimpleTestCase):
    @parameterized.expand(
        [
            ("8.4 billion", 8_400_000_000),
            ("1.2 million", 1_200_000),
            ("12,345", 12_345),
            ("0", 0),
        ]
    )
    def test_row_counts_read_as_words_above_a_million(self, expected: str, rows: int) -> None:
        self.assertEqual(format_rows(rows), expected)

    @parameterized.expand(
        [
            ("well above the ratio", 3_000_000_000, 3_000_000_000, True),
            ("exactly at the ratio", 100, 1000, True),
            ("below the ratio: something else pruned the read", 99, 1000, False),
            ("no count available", 3_000_000_000, None, False),
        ]
    )
    def test_event_gate(self, _name: str, rows_read: int, events_in_range: int | None, expected: bool) -> None:
        measurements = ScanMeasurements(rows_read=rows_read, duration_ms=6000, events_in_range=events_in_range)

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

    def test_no_event_filter_message(self) -> None:
        warning = build_warning(
            kind=FindingKind.NO_EVENT_FILTER,
            measurements=ScanMeasurements(rows_read=3_000_000_000, duration_ms=6000),
        )

        self.assertEqual(warning.type, "query_scan")
        self.assertEqual(
            warning.message,
            "This query read every event in its date range: 3.0 billion rows in 6.0 s. If the question "
            "is about specific events, add `WHERE event IN ('…')` naming them.",
        )
        self.assertEqual(warning.rows_read, 3_000_000_000)

    def test_event_filter_not_used_message_names_the_reason_and_quotes_the_clause(self) -> None:
        warning = build_warning(
            kind=FindingKind.EVENT_FILTER_NOT_USED,
            reason=FindingReason.IN_OR,
            measurements=ScanMeasurements(rows_read=8_400_000_000, duration_ms=19_000),
            clause="properties.plan = 'pro' or event = 'upgrade'",
            evidence="ClickHouse used the primary key columns team_id, toDate(timestamp).",
        )

        self.assertEqual(
            warning.message,
            "This query has an event filter, but it is inside an OR with another condition, so ClickHouse "
            "could not use it. It read 8.4 billion rows in 19.0 s. Put the event filter outside the OR: "
            "`WHERE event IN ('…') AND (… OR …)`.",
        )
        self.assertEqual(warning.clause, "properties.plan = 'pro' or event = 'upgrade'")
        self.assertEqual(warning.evidence, "ClickHouse used the primary key columns team_id, toDate(timestamp).")

    @parameterized.expand(
        [
            (
                "with a known span",
                250,
                "This query has no start date, so it read 40.0 billion rows across 250 days of data in 40.0 s.",
            ),
            (
                "with no span from the count",
                None,
                "This query has no start date, so it read 40.0 billion rows across all your data in 40.0 s.",
            ),
        ]
    )
    def test_no_start_date_message(self, _name: str, days: int | None, expected_lead: str) -> None:
        warning = build_warning(
            kind=FindingKind.NO_START_DATE,
            measurements=ScanMeasurements(rows_read=40_000_000_000, duration_ms=40_000, days=days),
        )

        self.assertTrue(warning.message.startswith(expected_lead), warning.message)

    @parameterized.expand(
        [
            (FindingKind.NO_EVENT_FILTER, None),
            (FindingKind.EVENT_FILTER_NOT_USED, FindingReason.WRAPPED),
            (FindingKind.NO_START_DATE, None),
            (FindingKind.NO_START_DATE, FindingReason.FILTERS),
            (FindingKind.PERSONS_JOIN, None),
            (FindingKind.ALL_EVENTS, None),
            (FindingKind.ALL_TIME, None),
        ]
    )
    def test_a_killed_run_reports_what_it_read_before_the_kill(
        self, kind: FindingKind, reason: FindingReason | None
    ) -> None:
        warning = build_warning(
            kind=kind,
            reason=reason,
            measurements=ScanMeasurements(
                rows_read=8_400_000_000, duration_ms=19_000, killed=True, person_rows=150_000_000, days=250
            ),
        )

        self.assertIn("ClickHouse stopped it after 19.0 s, having read 8.4 billion rows.", warning.message)

    def test_persons_join_message_names_the_person_count(self) -> None:
        warning = build_warning(
            kind=FindingKind.PERSONS_JOIN,
            measurements=ScanMeasurements(rows_read=153_000_000, duration_ms=3000, person_rows=150_000_000),
        )

        self.assertEqual(
            warning.message,
            "This query joins the persons table, which reads all 150.0 million person rows on every run. "
            "Read person properties from the events table instead, for example `person.properties.email`.",
        )


class TestSettingsAnalysis(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "all events over the ratio",
                {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": None}]},
                700_000_000,
                1_000_000_000,
                ["all_events"],
            ),
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
                "all time only",
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
                {"kind": "RetentionQuery", "series": [{"kind": "EventsNode", "event": None}]},
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
