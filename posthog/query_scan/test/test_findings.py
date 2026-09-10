from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.query_scan.findings import (
    FindingKind,
    FindingReason,
    ScanMeasurements,
    build_warning,
    explain_evidence,
    format_rows,
)

MEASUREMENTS = ScanMeasurements(rows_read=8_400_000_000, duration_ms=19_000)


class TestFindings(SimpleTestCase):
    @parameterized.expand([("8.4 billion", 8_400_000_000), ("12,345", 12_345)])
    def test_row_counts_read_as_words_above_a_million(self, expected: str, rows: int) -> None:
        self.assertEqual(format_rows(rows), expected)

    @parameterized.expand(
        [
            (FindingKind.NO_EVENT_FILTER, None, "HogQLQuery", "add `WHERE event IN", "add an event filter"),
            (
                FindingKind.NO_EVENT_FILTER,
                None,
                "TrendsQuery",
                "This insight looks at all events",
                "instead of All events",
            ),
            (FindingKind.NO_START_DATE, None, "HogQLQuery", "add `timestamp >= now()", "relative to now"),
            (
                FindingKind.NO_START_DATE,
                FindingReason.FILTERS,
                "HogQLQuery",
                "No date range is set on this insight or dashboard",
                "The SQL does not need to change",
            ),
            (FindingKind.NO_START_DATE, None, "TrendsQuery", "This insight has no start date", "instead of All time"),
            (FindingKind.PERSONS_JOIN, None, "HogQLQuery", "joins the persons table", "person.properties.email"),
        ]
    )
    def test_copy_switches_between_sql_and_insight_wording(
        self,
        kind: FindingKind,
        reason: FindingReason | None,
        query_kind: str,
        message_contains: str,
        fix_contains: str,
    ) -> None:
        warning = build_warning(kind=kind, reason=reason, query_kind=query_kind, measurements=MEASUREMENTS)

        self.assertEqual(warning.type, "query_scan")
        self.assertEqual(warning.kind, kind)
        self.assertIn(message_contains, warning.message)
        self.assertIn(fix_contains, warning.fix)
        self.assertEqual(warning.rows_read, 8_400_000_000)
        self.assertEqual(warning.duration_ms, 19_000)

    @parameterized.expand(
        [
            (
                "keys and granule counts",
                ("team_id", "toDate(timestamp)"),
                5_582_406,
                362_907,
                None,
                "ClickHouse's index used team_id, toDate(timestamp) and kept 362,907 of 5,582,406 granules.",
            ),
            (
                "no columns used",
                (),
                100,
                100,
                None,
                "ClickHouse's index used no columns and kept 100 of 100 granules.",
            ),
            (
                "a subquery finding names the subquery",
                ("team_id",),
                9_366_597,
                79_160,
                0,
                "In subquery 1: ClickHouse's index used team_id and kept 79,160 of 9,366,597 granules.",
            ),
        ]
    )
    def test_evidence_renders_keys_and_granule_counts(
        self,
        _name: str,
        keys: tuple[str, ...],
        before: int | None,
        after: int | None,
        subquery_index: int | None,
        expected: str,
    ) -> None:
        self.assertEqual(explain_evidence(keys, before=before, after=after, subquery_index=subquery_index), expected)
