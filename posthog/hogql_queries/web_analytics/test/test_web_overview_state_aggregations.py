import math
from datetime import datetime

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person

from posthog.schema import CompareFilter, DateRange, WebOverviewQuery

from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.transforms.state_aggregations import (
    transform_query_to_state_aggregations,
    wrap_state_query_in_merge_query,
)

from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.models.utils import uuid7


class TestWebOverviewStateTransform(ClickhouseTestMixin, APIBaseTest):
    """Test that web overview queries work correctly with state transformations."""

    QUERY_TIMESTAMP = "2025-01-29"

    def _create_events(self, data, event="$pageview"):
        person_result = []
        for id, timestamps in data:
            with freeze_time(timestamps[0][0]):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[id],
                        properties={
                            "name": id,
                            **({"email": "test@posthog.com"} if id == "test" else {}),
                        },
                    )
                )
            for timestamp, session_id, *extra in timestamps:
                url = None
                elements = None
                if event == "$pageview":
                    url = extra[0] if extra else None
                properties = {
                    "$session_id": session_id,
                    "$current_url": url,
                }
                if len(extra) > 1 and isinstance(extra[1], dict):
                    properties.update(extra[1])

                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=id,
                    timestamp=timestamp,
                    properties=properties,
                    elements=elements,
                )
        return person_result

    def _run_web_overview_with_aggregate_state(
        self,
        date_from: str,
        date_to: str,
        compare: bool = False,
    ):
        """Run the web overview query and return both original and state-transformed results."""
        with freeze_time(self.QUERY_TIMESTAMP):
            query = WebOverviewQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                properties=[],
                compareFilter=CompareFilter(compare=compare) if compare else None,
                filterTestAccounts=False,
            )
            runner = WebOverviewQueryRunner(team=self.team, query=query)
            original_query_ast = runner.to_query()

            # Execute original query
            context_original = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
            original_sql, _ = prepare_and_print_ast(original_query_ast, context=context_original, dialect="clickhouse")
            original_result = sync_execute(original_sql, context_original.values)

            # Full transformation (agg -> state -> merge)
            state_query_ast = transform_query_to_state_aggregations(original_query_ast)
            wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)

            # Execute transformed query
            context_transformed = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
            transformed_sql, _ = prepare_and_print_ast(
                wrapper_query_ast, context=context_transformed, dialect="clickhouse"
            )
            transformed_result = sync_execute(transformed_sql, context_transformed.values)

            return original_result, transformed_result

    def _compare_results(self, result1, result2):
        """Utility function to compare the two query results, we sometimes face NaN and None values which do happen on this query."""
        if len(result1) != len(result2):
            return False

        for row1, row2 in zip(result1, result2):
            if len(row1) != len(row2):
                return False

            for val1, val2 in zip(row1, row2):
                # Handle NaN values - consider NaN values equal to each other
                if isinstance(val1, float) and isinstance(val2, float) and math.isnan(val1) and math.isnan(val2):
                    continue
                # Consider None and NaN as equivalent
                elif (val1 is None and isinstance(val2, float) and math.isnan(val2)) or (
                    val2 is None and isinstance(val1, float) and math.isnan(val1)
                ):
                    continue
                # Check if both are None
                elif val1 is None and val2 is None:
                    continue
                # Compare other values normally
                elif val1 != val2:
                    return False

        return True

    def _create_test_data(self):
        timestamp1 = int(datetime.fromisoformat("2023-12-01").timestamp() * 1000)
        timestamp2 = int(datetime.fromisoformat("2023-12-02").timestamp() * 1000)
        timestamp3 = int(datetime.fromisoformat("2023-12-03").timestamp() * 1000)

        s1 = str(uuid7(timestamp1))
        s2 = str(uuid7(timestamp2))
        s3 = str(uuid7(timestamp3))

        return self._create_events(
            [
                (
                    "user1",
                    [
                        ("2023-12-01", s1, "https://example.com/page1"),
                        ("2023-12-01", s1, "https://example.com/page2", {"$session_duration": 300}),
                    ],
                ),
                ("user2", [("2023-12-02", s2, "https://example.com/page1")]),
                (
                    "user3",
                    [
                        ("2023-12-03", s3, "https://example.com/page1"),
                        ("2023-12-03", s3, "https://example.com/page2", {"$session_duration": 600}),
                    ],
                ),
            ]
        )

    def test_web_overview_query_without_compare_period(self):
        self._create_test_data()

        original_result, transformed_result = self._run_web_overview_with_aggregate_state("2023-12-01", "2023-12-03")

        self.assertTrue(
            self._compare_results(original_result, transformed_result),
            f"Results differ:\nOriginal: {original_result}\nTransformed: {transformed_result}",
        )

    def test_web_overview_query_with_compare_period(self):
        self._create_test_data()

        original_result, transformed_result = self._run_web_overview_with_aggregate_state(
            "2023-12-01", "2023-12-03", compare=True
        )

        self.assertTrue(
            self._compare_results(original_result, transformed_result),
            f"Results differ:\nOriginal: {original_result}\nTransformed: {transformed_result}",
        )
