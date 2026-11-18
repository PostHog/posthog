from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import QueryScanFindingKind, QueryScanFixLocation

from posthog.query_scan.findings import (
    ASSISTANT_GOAL,
    ASSISTANT_RULES,
    FindingCause,
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
            # cause keeps its own guidance, including whether exploration helps and which query to run.
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                {},
                "HogQLQuery",
                "add `WHERE event IN",
                "The query names no events",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                {"cause": FindingCause.EVENT_FILTER_INSIDE_OR},
                "HogQLQuery",
                "names events only inside an OR",
                "for what the other branch matches",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                {"cause": FindingCause.EVENT_WRAPPED_IN_FUNCTION},
                "HogQLQuery",
                "wraps `event` in a",
                "SELECT DISTINCT event",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                {"cause": FindingCause.EVENT_FILTER_ONLY_EXCLUDES},
                "HogQLQuery",
                "only excludes",
                "replace the exclusion with `event IN",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                {"cause": FindingCause.EVENT_COMPARED_TO_COLUMN},
                "HogQLQuery",
                "compares `event` to another",
                "no fixed name to prune on",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                {"cause": FindingCause.EVENT_FILTER_NOT_USED_BY_CLICKHOUSE},
                "HogQLQuery",
                "has an event filter",
                "into the WHERE of the events read",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                {"cause": FindingCause.PROPERTY_FILTER_WITHOUT_EVENT},
                "HogQLQuery",
                "narrows events by a property but names no events",
                "which events carry the property",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                {"cause": FindingCause.UNFILTERED_HELPER_READ},
                "HogQLQuery",
                "its largest read of the events table has no event filter",
                "Add an event filter to the unfiltered read",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                {"by_design": True},
                "HogQLQuery",
                "reads all events by design",
                "do not propose one",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                {},
                "TrendsQuery",
                "This insight looks at all events",
                "instead of All events",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                {"cause": FindingCause.PROPERTY_FILTER_WITHOUT_EVENT},
                "TrendsQuery",
                "looks at all events and filters them by a property",
                "pick them in the series",
            ),
            (
                QueryScanFindingKind.NO_EVENT_FILTER,
                {"by_design": True},
                "TrendsQuery",
                "looks at all events by design",
                "Do not propose one",
            ),
            (
                QueryScanFindingKind.NO_START_DATE,
                {},
                "HogQLQuery",
                "add `timestamp >= now()",
                "relative time bound",
            ),
            (
                QueryScanFindingKind.NO_START_DATE,
                {"fix_location": QueryScanFixLocation.INSIGHT_DATE_RANGE},
                "HogQLQuery",
                "The date range on this insight or dashboard has no start date",
                "Do not edit the SQL",
            ),
            (
                QueryScanFindingKind.NO_START_DATE,
                {"fix_location": QueryScanFixLocation.DASHBOARD_DATE_FILTER},
                "HogQLQuery",
                "The dashboard's date filter is set to All time",
                "change the dashboard's date filter",
            ),
            (
                QueryScanFindingKind.NO_START_DATE,
                {"cause": FindingCause.START_DATE_NOT_USED_BY_CLICKHOUSE},
                "HogQLQuery",
                "has a start date, but it could not be used",
                "add a fixed relative bound beside it",
            ),
            (
                QueryScanFindingKind.NO_START_DATE,
                {"by_design": True},
                "HogQLQuery",
                "finds a first event ever",
                "Do not propose a time bound",
            ),
            (
                QueryScanFindingKind.NO_START_DATE,
                {},
                "TrendsQuery",
                "This insight has no start date",
                "instead of All time",
            ),
            (
                QueryScanFindingKind.NO_START_DATE,
                {"fix_location": QueryScanFixLocation.DASHBOARD_DATE_FILTER},
                "TrendsQuery",
                "overrides the date range on this insight",
                "tell the person to change the dashboard's date filter",
            ),
            (
                QueryScanFindingKind.NO_START_DATE,
                {"by_design": True},
                "TrendsQuery",
                "finds each person's first event",
                "Do not propose a date range change",
            ),
            (
                QueryScanFindingKind.PERSONS_JOIN,
                {},
                "HogQLQuery",
                "joins the persons table",
                "person.properties.x",
            ),
            (
                QueryScanFindingKind.PERSONS_JOIN,
                {},
                "TrendsQuery",
                'PostHog recommends "Use person properties from the time of the event"',
                "do not propose an edit",
            ),
        ]
    )
    def test_copy_switches_between_sql_and_insight_wording(
        self,
        kind: QueryScanFindingKind,
        facts: dict[str, object],
        query_kind: str,
        message_contains: str,
        fix_contains: str,
    ) -> None:
        warning = build_warning(kind=kind, query_kind=query_kind, **facts)  # type: ignore[arg-type]

        self.assertEqual(warning.kind, kind)
        self.assertIn(message_contains, warning.message)
        self.assertIn(fix_contains, warning.fix)

    @parameterized.expand(
        [
            (QueryScanFindingKind.NO_EVENT_FILTER, {}, True),
            (QueryScanFindingKind.NO_EVENT_FILTER, {"query_kind": "TrendsQuery"}, False),
            (QueryScanFindingKind.NO_EVENT_FILTER, {"cause": FindingCause.EVENT_FILTER_INSIDE_OR}, True),
            (QueryScanFindingKind.NO_EVENT_FILTER, {"cause": FindingCause.EVENT_FILTER_ONLY_EXCLUDES}, True),
            (QueryScanFindingKind.NO_EVENT_FILTER, {"cause": FindingCause.EVENT_COMPARED_TO_COLUMN}, False),
            (QueryScanFindingKind.NO_EVENT_FILTER, {"by_design": True}, False),
            (QueryScanFindingKind.NO_START_DATE, {}, True),
            (QueryScanFindingKind.NO_START_DATE, {"by_design": True}, False),
            (QueryScanFindingKind.NO_START_DATE, {"view_name": "v_active"}, True),
            (QueryScanFindingKind.PERSONS_JOIN, {}, True),
            (QueryScanFindingKind.PERSONS_JOIN, {"query_kind": "TrendsQuery"}, False),
        ]
    )
    def test_actionable_follows_the_facts(
        self, kind: QueryScanFindingKind, facts: dict[str, object], expected: bool
    ) -> None:
        warning = build_warning(**{"kind": kind, "query_kind": "HogQLQuery", **facts})  # type: ignore[arg-type]

        self.assertIs(warning.actionable, expected)

    def test_the_subject_names_the_subquery_or_the_view(self) -> None:
        in_subquery = build_warning(kind=QueryScanFindingKind.NO_START_DATE, query_kind="HogQLQuery", subquery_index=1)
        in_view = build_warning(kind=QueryScanFindingKind.NO_START_DATE, query_kind="HogQLQuery", view_name="v_active")

        self.assertIn("Subquery 2 of this query has no start date", in_subquery.message)
        self.assertIn("subquery 2", in_subquery.fix)
        self.assertIn("The view `v_active` inside this query has no start date", in_view.message)
        self.assertIn("the change goes in the view", in_view.message)
        self.assertIn("Do not edit this query for it", in_view.fix)

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
            cause=FindingCause.EVENT_FILTER_INSIDE_OR,
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
            kind=QueryScanFindingKind.NO_START_DATE,
            fix_location=QueryScanFixLocation.INSIGHT_DATE_RANGE,
            query_kind="HogQLQuery",
        )
        in_query = build_warning(
            kind=QueryScanFindingKind.NO_EVENT_FILTER,
            cause=FindingCause.EVENT_FILTER_INSIDE_OR,
            query_kind="HogQLQuery",
        )

        by_design = build_warning(kind=QueryScanFindingKind.NO_EVENT_FILTER, by_design=True, query_kind="HogQLQuery")

        self.assertIsNone(assistant_prompt([on_insight], fixable_only=True))
        self.assertIsNone(assistant_prompt([on_insight, by_design], fixable_only=True))
        fixable = assistant_prompt([on_insight, in_query], fixable_only=True)
        assert fixable is not None
        self.assertNotIn("no_start_date", fixable)
        self.assertIn("- no_event_filter (in_or):", fixable)
        # The assistant's own block keeps it, since the assistant can tell the person where to set the range.
        full = assistant_prompt([on_insight])
        assert full is not None
        self.assertIn("- no_start_date:", full)

    def test_fixable_only_needs_an_actionable_finding_and_keeps_the_by_design_guidance(self) -> None:
        by_design = build_warning(kind=QueryScanFindingKind.NO_START_DATE, by_design=True, query_kind="HogQLQuery")
        actionable = build_warning(
            kind=QueryScanFindingKind.NO_EVENT_FILTER,
            cause=FindingCause.EVENT_WRAPPED_IN_FUNCTION,
            query_kind="HogQLQuery",
        )

        self.assertIsNone(assistant_prompt([by_design], fixable_only=True))
        prompt = assistant_prompt([by_design, actionable], fixable_only=True)
        assert prompt is not None
        self.assertIn("- no_start_date:", prompt)
        self.assertIn("- no_event_filter (wrapped):", prompt)
