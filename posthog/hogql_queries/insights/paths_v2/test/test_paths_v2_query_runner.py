from abc import ABC
from datetime import datetime
from uuid import UUID

from freezegun.api import freeze_time
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.paths_v2.paths_v2_query_runner import (
    POSTHOG_OTHER,
    POSTHOG_DROPOFF,
    PathsV2QueryRunner,
)
from posthog.schema import (
    DateRange,
    PathsV2Filter,
    PathsV2Item,
    PathsV2Query,
    EventsNode,
    EventPropertyFilter,
    PropertyOperator,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
)
from posthog.test.test_journeys import journeys_for
import pytz
import pytest


class SharedSetup(ClickhouseTestMixin, APIBaseTest, ABC):
    def _get_query_runner(self, query: PathsV2Query | None = None) -> PathsV2QueryRunner:
        if query is None:
            query = PathsV2Query()
        return PathsV2QueryRunner(team=self.team, query=query)


class TestPathsV2(SharedSetup):
    maxDiff = None

    def test_simple_path_query(self):
        _ = journeys_for(
            team=self.team,
            events_by_person={
                # User 1 (Full Funnel)
                "person1": [
                    {"event": "Landing Page", "timestamp": "2023-03-10 12:00:00"},
                    {"event": "Product View", "timestamp": "2023-03-10 12:05:00"},
                    {"event": "Add to Cart", "timestamp": "2023-03-10 12:10:00"},
                    {"event": "Checkout", "timestamp": "2023-03-10 12:15:00"},
                    {"event": "Purchase", "timestamp": "2023-03-10 12:20:00"},
                ],
                # User 2 (Search before purchase)
                "person2": [
                    {"event": "Landing Page", "timestamp": "2023-03-11 11:30:00"},
                    {"event": "Search", "timestamp": "2023-03-11 11:32:00"},
                    {"event": "Product View", "timestamp": "2023-03-11 11:35:00"},
                    {"event": "Add to Cart", "timestamp": "2023-03-11 11:38:00"},
                    {"event": "Checkout", "timestamp": "2023-03-11 11:42:00"},
                    {"event": "Purchase", "timestamp": "2023-03-11 11:45:00"},
                ],
                # User 3 (Abandoned Cart)
                "person3": [
                    {"event": "Landing Page", "timestamp": "2023-03-12 10:00:00"},
                    {"event": "Product View", "timestamp": "2023-03-12 10:02:00"},
                    {"event": "Add to Cart", "timestamp": "2023-03-12 10:05:00"},
                ],
                # User 4 (Bounced)
                "person4": [
                    {"event": "Landing Page", "timestamp": "2023-03-13 09:00:00"},
                ],
            },
        )

        with freeze_time("2023-03-13T12:00:00Z"):
            filter = PathsV2Filter(maxRowsPerStep=10, maxSteps=10)
            query = PathsV2Query(pathsV2Filter=filter)
            query_runner = self._get_query_runner(query=query)

            response = query_runner.calculate()

        self.assertEqual(
            response.results,
            [
                # step 1
                PathsV2Item(step_index=1, source_step="Landing Page", target_step="Product View", value=2.0),
                PathsV2Item(step_index=1, source_step="Landing Page", target_step="Search", value=1.0),
                PathsV2Item(step_index=1, source_step="Landing Page", target_step=POSTHOG_DROPOFF, value=1.0),
                # step 2
                PathsV2Item(step_index=2, source_step="Product View", target_step="Add to Cart", value=2.0),
                PathsV2Item(step_index=2, source_step="Search", target_step="Product View", value=1.0),
                # step 3
                PathsV2Item(step_index=3, source_step="Product View", target_step="Add to Cart", value=1.0),
                PathsV2Item(step_index=3, source_step="Add to Cart", target_step="Checkout", value=1.0),
                PathsV2Item(step_index=3, source_step="Add to Cart", target_step=POSTHOG_DROPOFF, value=1.0),
                # step 4
                PathsV2Item(step_index=4, source_step="Add to Cart", target_step="Checkout", value=1.0),
                PathsV2Item(step_index=4, source_step="Checkout", target_step="Purchase", value=1.0),
                # step 5
                PathsV2Item(step_index=5, source_step="Checkout", target_step="Purchase", value=1.0),
                PathsV2Item(step_index=5, source_step="Purchase", target_step=POSTHOG_DROPOFF, value=1.0),
                # step 6
                PathsV2Item(step_index=6, source_step="Purchase", target_step=POSTHOG_DROPOFF, value=1.0),
            ],
        )

    def test_aggregates_nodes_exceeding_limit(self):
        _ = journeys_for(
            team=self.team,
            events_by_person={
                # 6x a1 -> b1
                "person1": [{"event": "a1"}, {"event": "b1"}],
                "person2": [{"event": "a1"}, {"event": "b1"}],
                "person3": [{"event": "a1"}, {"event": "b1"}],
                "person4": [{"event": "a1"}, {"event": "b1"}],
                "person5": [{"event": "a1"}, {"event": "b1"}],
                "person6": [{"event": "a1"}, {"event": "b1"}],
                # 5x a1 -> b2
                "person7": [{"event": "a1"}, {"event": "b2"}],
                "person8": [{"event": "a1"}, {"event": "b2"}],
                "person9": [{"event": "a1"}, {"event": "b2"}],
                "person10": [{"event": "a1"}, {"event": "b2"}],
                "person11": [{"event": "a1"}, {"event": "b2"}],
                # 4x a2 -> dropoff
                "person12": [{"event": "a2"}],
                "person13": [{"event": "a2"}],
                "person14": [{"event": "a2"}],
                "person15": [{"event": "a2"}],
                # 3x a3 -> a3
                "person16": [{"event": "a3"}, {"event": "a3"}],
                "person17": [{"event": "a3"}, {"event": "a3"}],
                "person18": [{"event": "a3"}, {"event": "a3"}],
                # 2x a4 (grouped into "other") -> b1
                "person19": [{"event": "a4"}, {"event": "b1"}],
                "person20": [{"event": "a4"}, {"event": "b1"}],
                # 1x a5 (grouped into "other") -> dropoff
                "person21": [{"event": "a5"}],
            },
        )
        filter = PathsV2Filter(maxRowsPerStep=3)
        query = PathsV2Query(pathsV2Filter=filter)
        query_runner = self._get_query_runner(query=query)

        response = query_runner.calculate()

        self.assertEqual(
            [item for item in response.results if item.step_index == 1],
            [
                PathsV2Item(step_index=1, source_step="a1", target_step="b1", value=6),
                PathsV2Item(step_index=1, source_step="a1", target_step="b2", value=5),
                PathsV2Item(step_index=1, source_step="a3", target_step="a3", value=3),
                PathsV2Item(step_index=1, source_step=POSTHOG_OTHER, target_step="b1", value=2),
                PathsV2Item(step_index=1, source_step="a2", target_step=POSTHOG_DROPOFF, value=4),
                PathsV2Item(step_index=1, source_step=POSTHOG_OTHER, target_step=POSTHOG_DROPOFF, value=1),
            ],
        )

    def test_aggregates_nodes_grouping(self):
        _ = journeys_for(
            team=self.team,
            events_by_person={
                # 2x a1 -> b1
                "person1": [{"event": "a1"}, {"event": "b1"}],
                "person2": [{"event": "a1"}, {"event": "b1"}],
                # 1x a2 -> b2
                "person3": [{"event": "a2"}, {"event": "b2"}],
                # 1x a3 -> b3
                "person4": [{"event": "a3"}, {"event": "b3"}],
            },
        )

        filter = PathsV2Filter(maxRowsPerStep=1)
        query = PathsV2Query(pathsV2Filter=filter)
        query_runner = self._get_query_runner(query=query)

        response = query_runner.calculate()

        self.assertEqual(
            [item for item in response.results if item.step_index == 1],
            [
                PathsV2Item(step_index=1, source_step="a1", target_step="b1", value=2),
                PathsV2Item(step_index=1, source_step=POSTHOG_OTHER, target_step=POSTHOG_OTHER, value=2),
            ],
        )

    def test_sorts_results(self):
        _ = journeys_for(
            team=self.team,
            events_by_person={
                # 1x a1 -> b1
                "person1": [{"event": "a1"}, {"event": "b1"}],
                # 2x a2 -> b2
                "person2": [{"event": "a2"}, {"event": "b2"}],
                "person3": [{"event": "a2"}, {"event": "b2"}],
                # 1x dropoff
                "person4": [{"event": "a2"}],
                # 1x other
                "person5": [{"event": "a2"}, {"event": "b3"}],
            },
        )

        filter = PathsV2Filter(maxRowsPerStep=2)
        query = PathsV2Query(pathsV2Filter=filter)
        query_runner = self._get_query_runner(query=query)
        response = query_runner.calculate()

        self.assertEqual(
            [item for item in response.results if item.step_index == 1],
            [
                PathsV2Item(step_index=1, source_step="a2", target_step="b2", value=2),
                PathsV2Item(step_index=1, source_step="a1", target_step="b1", value=1),
                PathsV2Item(step_index=1, source_step="a2", target_step=POSTHOG_DROPOFF, value=1),
                PathsV2Item(step_index=1, source_step="a2", target_step=POSTHOG_OTHER, value=1),
            ],
        )

    def test_collapses_events(self):
        _ = journeys_for(
            team=self.team,
            events_by_person={
                "person": [
                    {"event": "a"},
                    {"event": "b"},
                    {"event": "b"},
                    {"event": "c"},
                    {"event": "c"},
                ],
            },
        )

        # doesn't collapse when false
        filter = PathsV2Filter(collapseEvents=False, maxSteps=10)

        query = PathsV2Query(pathsV2Filter=filter)
        query_runner = self._get_query_runner(query=query)
        response = query_runner.calculate()

        self.assertEqual(
            response.results,
            [
                PathsV2Item(step_index=1.0, source_step="a", target_step="b", value=1.0),
                PathsV2Item(step_index=2.0, source_step="b", target_step="b", value=1.0),
                PathsV2Item(step_index=3.0, source_step="b", target_step="c", value=1.0),
                PathsV2Item(step_index=4.0, source_step="c", target_step="c", value=1.0),
                PathsV2Item(step_index=5.0, source_step="c", target_step=POSTHOG_DROPOFF, value=1.0),
            ],
        )

        # collapses when true
        filter = PathsV2Filter(collapseEvents=True)

        query = PathsV2Query(pathsV2Filter=filter)
        query_runner = self._get_query_runner(query=query)
        response = query_runner.calculate()

        self.assertEqual(
            response.results,
            [
                PathsV2Item(step_index=1.0, source_step="a", target_step="b", value=1.0),
                PathsV2Item(step_index=2.0, source_step="b", target_step="c", value=1.0),
                PathsV2Item(step_index=3.0, source_step="c", target_step=POSTHOG_DROPOFF, value=1.0),
            ],
        )

    @pytest.mark.skip(reason="TODO: pending start and end event implementation")
    def test_series(self):
        _ = journeys_for(
            team=self.team,
            events_by_person={
                "person": [
                    {"event": "a"},
                    {"event": "b"},
                    {"event": "b"},
                    {"event": "c"},
                    {"event": "c"},
                ],
            },
        )

        filter = PathsV2Filter()
        query = PathsV2Query(
            series=[
                EventsNode(
                    kind="EventsNode",
                    event="$identify",
                    name="$identify",
                    properties=[
                        EventPropertyFilter(
                            key="$browser", value=["Chrome"], operator=PropertyOperator.EXACT, type="event"
                        )
                    ],
                )
            ],
            pathsV2Filter=filter,
        )
        query_runner = self._get_query_runner(query=query)
        response = query_runner.calculate()

        self.assertEqual(
            response.results,
            [
                PathsV2Item(step_index=1.0, source_step="a", target_step="b", value=1.0),
                PathsV2Item(step_index=2.0, source_step="b", target_step="b", value=1.0),
                PathsV2Item(step_index=3.0, source_step="b", target_step="c", value=1.0),
                PathsV2Item(step_index=4.0, source_step="c", target_step="c", value=1.0),
                PathsV2Item(step_index=5.0, source_step="c", target_step=POSTHOG_DROPOFF, value=1.0),
            ],
        )


class TestPathsV2BaseEventsQuery(SharedSetup):
    maxDiff = None

    def test_event_base_query(self):
        pass

    def test_date_filters(self):
        _ = journeys_for(
            team=self.team,
            events_by_person={
                "person1": [
                    {"event": "event1", "timestamp": "2023-03-01 12:00:00"},
                    {"event": "event2", "timestamp": "2023-03-02 12:00:00"},
                    {"event": "event3", "timestamp": "2023-03-03 12:00:00"},
                ],
            },
        )
        query = PathsV2Query(dateRange=DateRange(date_from="2023-03-02", date_to="2023-03-02"))

        query_runner = self._get_query_runner(query=query)
        event_base_query = query_runner._event_base_query()
        response = execute_hogql_query(query=event_base_query, team=self.team)

        self.assertEqual(
            response.results,
            [
                (
                    datetime(2023, 3, 2, 12, 0, tzinfo=pytz.UTC),
                    UUID("19817248-b1a1-f231-a0f6-a530155cbd20"),
                    "event2",
                ),
            ],
        )

    def test_property_filters(self):
        _ = journeys_for(
            team=self.team,
            events_by_person={
                "person1": [
                    {"event": "event1", "timestamp": "2023-03-12 12:00:00", "properties": {"$browser": "Chrome"}},
                    {"event": "event2", "timestamp": "2023-03-12 12:00:00", "properties": {"$browser": "Firefox"}},
                ],
            },
        )
        query = PathsV2Query(
            properties=[
                EventPropertyFilter(key="$browser", value=["Chrome"], operator=PropertyOperator.EXACT, type="event")
            ],
        )

        with freeze_time("2023-03-13T12:00:00Z"):
            query_runner = self._get_query_runner(query=query)
            event_base_query = query_runner._event_base_query()
            response = execute_hogql_query(query=event_base_query, team=self.team)

        self.assertEqual(
            response.results,
            [(datetime(2023, 3, 12, 12, 0, tzinfo=pytz.UTC), UUID("231700cd-f48e-754a-6bf1-744a9464be9e"), "event1")],
        )

    def test_test_account_filters(self):
        self.team.test_account_filters = [{"key": "$browser", "value": "Chrome", "operator": "exact", "type": "event"}]
        self.team.save()
        _ = journeys_for(
            team=self.team,
            events_by_person={
                "person1": [
                    {"event": "event1", "timestamp": "2023-03-12 12:00:00", "properties": {"$browser": "Chrome"}},
                    {"event": "event2", "timestamp": "2023-03-12 12:00:00", "properties": {"$browser": "Firefox"}},
                ],
            },
        )
        query = PathsV2Query(filterTestAccounts=True)

        with freeze_time("2023-03-13T12:00:00Z"):
            query_runner = self._get_query_runner(query=query)
            event_base_query = query_runner._event_base_query()
            response = execute_hogql_query(query=event_base_query, team=self.team)

        self.assertEqual(
            response.results,
            [(datetime(2023, 3, 12, 12, 0, tzinfo=pytz.UTC), UUID("c6d7a3d6-6307-9297-248b-3569c2ae4c93"), "event1")],
        )

    @pytest.mark.skip(reason="TODO: pending start and end event implementation")
    def test_start_and_end_event(self):
        pass


class TestPathsV2PathsPerActorAsArrayQuery(SharedSetup):
    maxDiff = None

    def test_aggregates_items_into_arrays(self):
        _ = journeys_for(
            team=self.team,
            events_by_person={
                "person1": [
                    {"event": "event1", "timestamp": "2023-03-12 12:00:00"},
                    {"event": "event2", "timestamp": "2023-03-12 12:00:00"},
                ],
                "person2": [
                    {"event": "event3", "timestamp": "2023-03-12 12:00:00"},
                    {"event": "event4", "timestamp": "2023-03-12 12:00:00"},
                ],
            },
        )
        query = PathsV2Query(filterTestAccounts=True)

        with freeze_time("2023-03-13T12:00:00Z"):
            query_runner = self._get_query_runner(query=query)
            paths_per_actor_as_array_query = query_runner._paths_per_actor_as_array_query()
            response = execute_hogql_query(query=paths_per_actor_as_array_query, team=self.team)

        self.assertEqual(
            response.results,
            [(datetime(2023, 3, 12, 12, 0, tzinfo=pytz.UTC), UUID("c6d7a3d6-6307-9297-248b-3569c2ae4c93"), "event1")],
        )

    @pytest.mark.skip(reason="TODO: pending start and end event implementation")
    def test_start_and_end_event(self):
        pass
