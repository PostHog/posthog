from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import QueryScanFindingKind, QueryScanFindingReason

from posthog.query_scan.findings import (
    ASSISTANT_GOAL,
    ASSISTANT_RULES,
    assistant_prompt,
    build_warning,
    explain_evidence,
    format_rows,
)


class TestFindings(SimpleTestCase):
    @parameterized.expand([("8.4 billion", 8_400_000_000), ("12,345", 12_345)])
    def test_row_counts_read_as_words_above_a_million(self, expected: str, rows: int) -> None:
        self.assertEqual(format_rows(rows), expected)

    @parameterized.expand(
        [
            # The `message` is the human banner; the `fix` is the assistant-facing guidance. Each SQL
            # reason keeps its own guidance, including whether exploration helps and which query to run.
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                None,
                "HogQLQuery",
                "add `WHERE event IN",
                "The query names no events",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                QueryScanFindingReason.IN_OR,
                "HogQLQuery",
                "names events only inside an OR",
                "for what the other branch matches",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                QueryScanFindingReason.WRAPPED,
                "HogQLQuery",
                "wraps `event` in a",
                "SELECT DISTINCT event",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                QueryScanFindingReason.NEGATED,
                "HogQLQuery",
                "only excludes",
                "Do not run exploratory queries",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                QueryScanFindingReason.DYNAMIC,
                "HogQLQuery",
                "compares `event` to another",
                "no fixed name to prune on",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                QueryScanFindingReason.NOT_PRUNED,
                "HogQLQuery",
                "has an event filter",
                "into the WHERE of the events read",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                None,
                "TrendsQuery",
                "This insight looks at all events",
                "instead of All events",
            ),
            (
                QueryScanFindingKind.NO_START_DATE,
                None,
                "HogQLQuery",
                "add `timestamp >= now()",
                "relative time bound",
            ),
            (
                QueryScanFindingKind.NO_START_DATE,
                QueryScanFindingReason.FILTERS,
                "HogQLQuery",
                "No date range is set on this insight or dashboard",
                "Do not edit the SQL",
            ),
            (
                QueryScanFindingKind.NO_START_DATE,
                None,
                "TrendsQuery",
                "This insight has no start date",
                "instead of All time",
            ),
            (
                QueryScanFindingKind.PERSONS_JOIN,
                None,
                "HogQLQuery",
                "joins the persons table",
                "person.properties.x",
            ),
        ]
    )
    def test_copy_switches_between_sql_and_insight_wording(
        self,
        kind: QueryScanFindingKind,
        reason: QueryScanFindingReason | None,
        query_kind: str,
        message_contains: str,
        fix_contains: str,
    ) -> None:
        warning = build_warning(kind=kind, reason=reason, query_kind=query_kind)

        self.assertEqual(warning.type, "query_scan")
        self.assertEqual(warning.kind, kind)
        self.assertIn(message_contains, warning.message)
        self.assertIn(fix_contains, warning.fix)

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


class TestAssistantPrompt(SimpleTestCase):
    def test_goal_first_then_the_run_each_finding_and_the_rules(self) -> None:
        finding = build_warning(
            kind=QueryScanFindingKind.NO_EVENT_FILTER,
            reason=QueryScanFindingReason.IN_OR,
            query_kind="HogQLQuery",
            evidence="ClickHouse's index used team_id and kept 5 of 100 granules.",
        )

        prompt = assistant_prompt(
            [finding], rows_read=8_400_000_000, duration_ms=19_000, range_share=0.42, project_share=0.07
        )

        assert prompt is not None
        lines = prompt.splitlines()
        self.assertEqual(lines[0], ASSISTANT_GOAL)
        self.assertIn("This query read 8.4 billion rows in 19.0 s.", lines)
        self.assertIn("It read about 42% of the events in this date range.", lines)
        self.assertIn("It read about 7% of the project's events.", lines)
        self.assertIn(f"- no_event_filter (in_or): {finding.evidence} {finding.fix}", lines)
        self.assertEqual(lines[-1], ASSISTANT_RULES)

    @parameterized.expand(
        [
            ("with the run's numbers", 90, 400, "ClickHouse stopped this query after 0.4 s, having read 90 rows."),
            # The scan endpoint has no numbers for the run, only that it was stopped.
            ("without them", None, None, "ClickHouse stopped this query before it finished."),
        ]
    )
    def test_a_stopped_run_says_so(
        self, _name: str, rows_read: int | None, duration_ms: int | None, expected_line: str
    ) -> None:
        finding = build_warning(kind=QueryScanFindingKind.NO_START_DATE, query_kind="HogQLQuery")

        prompt = assistant_prompt([finding], rows_read=rows_read, duration_ms=duration_ms, killed=True)

        assert prompt is not None
        self.assertIn(expected_line, prompt.splitlines())
        self.assertNotIn("of the events in this date range", prompt)

    def test_fixable_only_leaves_out_a_finding_fixed_on_the_insight(self) -> None:
        # "Fix with AI" writes into the SQL, and a `{filters}` date range is set on the insight, so a
        # prompt for that finding alone would send the assistant to change nothing.
        on_insight = build_warning(
            kind=QueryScanFindingKind.NO_START_DATE, reason=QueryScanFindingReason.FILTERS, query_kind="HogQLQuery"
        )
        in_query = build_warning(kind=QueryScanFindingKind.NO_EVENT_FILTER, query_kind="HogQLQuery")

        self.assertIsNone(assistant_prompt([on_insight], fixable_only=True))
        fixable = assistant_prompt([on_insight, in_query], fixable_only=True)
        assert fixable is not None
        self.assertNotIn("no_start_date", fixable)
        self.assertIn("- no_event_filter:", fixable)
        # The assistant's own block keeps it, since the assistant can tell the person where to set the range.
        full = assistant_prompt([on_insight])
        assert full is not None
        self.assertIn("- no_start_date (filters):", full)
