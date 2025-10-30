"""
Test for breakdown with empty string, null, and missing properties.

This test validates that the trends query and actors query handle
null/empty/missing property values consistently, ensuring that events
with these property states are correctly counted and returned.

Regression test for: https://github.com/PostHog/posthog/issues/40577
"""

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person

from django.test import override_settings

from posthog.schema import (
    ActorsQuery,
    Breakdown,
    BreakdownFilter,
    DateRange,
    EventsNode,
    InsightActorsQuery,
    TrendsQuery,
)

from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.insights.trends.breakdown import BREAKDOWN_NULL_STRING_LABEL
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner


@override_settings(IN_UNIT_TESTING=True)
class TestTrendsBreakdownEmptyNullProperties(ClickhouseTestMixin, APIBaseTest):
    """Test breakdown behavior with null, empty string, and missing properties."""

    @freeze_time("2024-01-15T12:00:00Z")
    def test_breakdown_with_null_empty_and_missing_properties(self):
        """
        Test that breakdown correctly handles:
        1. Property value is null
        2. Property value is empty string
        3. Property is missing entirely

        All three cases should be grouped together in the "None" breakdown.
        """
        # Create persons
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["user_with_null"],
            properties={},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["user_with_empty_string"],
            properties={},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["user_with_missing"],
            properties={},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["user_with_value"],
            properties={},
        )

        # Create events with different property states
        # Event 1: Property value is explicit null
        _create_event(
            event="test_event",
            distinct_id="user_with_null",
            timestamp="2024-01-10 12:00:00",
            properties={"test_property": None},
            team=self.team,
        )

        # Event 2: Property value is empty string
        _create_event(
            event="test_event",
            distinct_id="user_with_empty_string",
            timestamp="2024-01-10 12:00:00",
            properties={"test_property": ""},
            team=self.team,
        )

        # Event 3: Property is missing entirely
        _create_event(
            event="test_event",
            distinct_id="user_with_missing",
            timestamp="2024-01-10 12:00:00",
            properties={"some_other_property": "value"},
            team=self.team,
        )

        # Event 4: Property has an actual value (for comparison)
        _create_event(
            event="test_event",
            distinct_id="user_with_value",
            timestamp="2024-01-10 12:00:00",
            properties={"test_property": "actual_value"},
            team=self.team,
        )

        # Create trends query with breakdown
        trends_query = TrendsQuery(
            series=[EventsNode(event="test_event")],
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-15"),
            breakdownFilter=BreakdownFilter(
                breakdown="test_property",
                breakdown_type="event",
            ),
        )

        # Execute trends query
        trends_runner = TrendsQueryRunner(query=trends_query, team=self.team)
        trends_result = trends_runner.calculate()
        breakdown_results = {r["breakdown_value"]: r["count"] for r in trends_result.results}

        # The "None" breakdown should have count of 3 (null, empty, missing)
        self.assertEqual(
            breakdown_results.get("$$_posthog_breakdown_null_$$"),
            3,
            "Trends query should count 3 events for None breakdown (null + empty string + missing property)",
        )

        # The "actual_value" breakdown should have count of 1
        self.assertEqual(
            breakdown_results.get("actual_value"),
            1,
            "Trends query should count 1 event for 'actual_value' breakdown",
        )

        # Now test the actors query for the "None" breakdown
        actors_query = ActorsQuery(
            source=InsightActorsQuery(
                source=trends_query,
                breakdown=BREAKDOWN_NULL_STRING_LABEL,
                day="2024-01-10",
            ),
            select=["actor", "event_count"],
            orderBy=["event_count DESC"],
        )

        actors_runner = ActorsQueryRunner(query=actors_query, team=self.team)
        actors_result = actors_runner.calculate()

        # Verify actors results
        self.assertEqual(
            len(actors_result.results),
            3,
            "Actors query should return 3 actors for None breakdown (null + empty string + missing property)",
        )

        # Extract the distinct IDs from results
        returned_distinct_ids = set()
        for result in actors_result.results:
            actor_data = result[0]  # First element is actor data
            if "distinct_ids" in actor_data:
                returned_distinct_ids.update(actor_data["distinct_ids"])

        # Verify all three users are returned
        self.assertEqual(
            returned_distinct_ids,
            {"user_with_null", "user_with_empty_string", "user_with_missing"},
            "Actors query should return all users with null, empty string, or missing property",
        )

    @freeze_time("2024-01-15T12:00:00Z")
    def test_multiple_breakdown_with_null_empty_and_missing_properties(self):
        """
        Test that multiple breakdowns correctly handle null/empty/missing properties.

        This tests the case where we break down by two properties, and both
        properties have null/empty/missing values.
        """
        # Create persons
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["user_none_none"],
            properties={},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["user_value_none"],
            properties={},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["user_none_value"],
            properties={},
        )

        # Event with both properties null/empty/missing (None, None)
        _create_event(
            event="test_event",
            distinct_id="user_none_none",
            timestamp="2024-01-10 12:00:00",
            properties={},  # Both properties missing
            team=self.team,
        )

        # Event with first property having value, second null (Value, None)
        _create_event(
            event="test_event",
            distinct_id="user_value_none",
            timestamp="2024-01-10 12:00:00",
            properties={"prop1": "value1"},  # prop2 missing
            team=self.team,
        )

        # Event with first property null, second having value (None, Value)
        _create_event(
            event="test_event",
            distinct_id="user_none_value",
            timestamp="2024-01-10 12:00:00",
            properties={"prop2": "value2"},  # prop1 missing
            team=self.team,
        )

        # Create trends query with multiple breakdowns
        trends_query = TrendsQuery(
            series=[EventsNode(event="test_event")],
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-15"),
            breakdownFilter=BreakdownFilter(
                breakdowns=[
                    Breakdown(property="prop1", type="event"),
                    Breakdown(property="prop2", type="event"),
                ]
            ),
        )

        # Execute trends query
        trends_runner = TrendsQueryRunner(query=trends_query, team=self.team)
        trends_result = trends_runner.calculate()

        # Find the (None, None) breakdown
        none_none_result = None
        for r in trends_result.results:
            breakdown_value = r["breakdown_value"]
            if (
                isinstance(breakdown_value, list)
                and len(breakdown_value) == 2
                and breakdown_value[0] == BREAKDOWN_NULL_STRING_LABEL
                and breakdown_value[1] == BREAKDOWN_NULL_STRING_LABEL
            ):
                none_none_result = r
                break

        self.assertIsNotNone(none_none_result, "Should have a (None, None) breakdown result")
        self.assertEqual(
            none_none_result["count"],
            1,
            "The (None, None) breakdown should have count of 1",
        )

        # Now test the actors query for the (None, None) breakdown
        insight_actors_query = InsightActorsQuery(
            source=trends_query,
            breakdown=[BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_NULL_STRING_LABEL],
            day="2024-01-10",
        )

        actors_query = ActorsQuery(
            source=insight_actors_query,
            select=["actor", "event_count"],
            orderBy=["event_count DESC"],
        )

        actors_runner = ActorsQueryRunner(query=actors_query, team=self.team)
        actors_result = actors_runner.calculate()

        # Verify actors results
        self.assertEqual(
            len(actors_result.results),
            1,
            "Actors query should return 1 actor for (None, None) breakdown",
        )

        # Extract the distinct ID
        actor_data = actors_result.results[0][0]
        if "distinct_ids" in actor_data:
            returned_distinct_ids = actor_data["distinct_ids"]
            self.assertIn(
                "user_none_none",
                returned_distinct_ids,
                "Actors query should return user_none_none for (None, None) breakdown",
            )
