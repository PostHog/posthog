from datetime import datetime, timedelta

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    BreakdownAttributionType,
    BreakdownFilter,
    BreakdownType,
    DateRange,
    EventPropertyFilter,
    EventsNode,
    FunnelConversionWindowTimeUnit,
    FunnelExclusionEventsNode,
    FunnelLayout,
    FunnelsFilter,
    FunnelsQuery,
    FunnelStepReference,
    FunnelVizType,
    IntervalType,
    PropertyOperator,
    StepOrderValue,
)

from posthog.constants import FunnelOrderType
from posthog.hogql_queries.insights.funnels import FunnelUDF
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.funnels.test.breakdown_cases import (
    FunnelStepResult,
    assert_funnel_results_equal,
    funnel_breakdown_group_test_factory,
    funnel_breakdown_test_factory,
)
from posthog.hogql_queries.insights.funnels.test.conversion_time_cases import funnel_conversion_time_test_factory
from posthog.hogql_queries.insights.funnels.test.test_funnel_persons import get_actors
from posthog.test.test_journeys import journeys_for

from products.event_definitions.backend.models.property_definition import PropertyDefinition


def unordered_funnels_query(
    *,
    series: list[EventsNode],
    date_from: str | None = None,
    date_to: str | None = None,
    breakdown: str | list[str] | None = None,
    breakdown_attribution_type: BreakdownAttributionType = BreakdownAttributionType.FIRST_TOUCH,
    breakdown_attribution_value: int | None = None,
    exclusions: list[FunnelExclusionEventsNode] | None = None,
    funnel_from_step: int | None = None,
    funnel_to_step: int | None = None,
    funnel_viz_type: FunnelVizType = FunnelVizType.STEPS,
    funnel_window_interval: int = 14,
    funnel_window_interval_unit: FunnelConversionWindowTimeUnit = FunnelConversionWindowTimeUnit.DAY,
) -> FunnelsQuery:
    return FunnelsQuery(
        breakdownFilter=BreakdownFilter(
            breakdown=breakdown,
            breakdown_type=BreakdownType.EVENT,
        ),
        dateRange=DateRange(
            date_from=date_from,
            date_to=date_to,
            explicitDate=False,
        ),
        filterTestAccounts=False,
        funnelsFilter=FunnelsFilter(
            breakdownAttributionType=breakdown_attribution_type,
            breakdownAttributionValue=breakdown_attribution_value,
            exclusions=exclusions or [],
            funnelFromStep=funnel_from_step,
            funnelOrderType=StepOrderValue.UNORDERED,
            funnelStepReference=FunnelStepReference.TOTAL,
            funnelToStep=funnel_to_step,
            funnelVizType=funnel_viz_type,
            funnelWindowInterval=funnel_window_interval,
            funnelWindowIntervalUnit=funnel_window_interval_unit,
            layout=FunnelLayout.VERTICAL,
            showValuesOnSeries=False,
        ),
        properties=[],
        series=series,
    )


class TestFunnelUnorderedStepsBreakdown(
    ClickhouseTestMixin,
    funnel_breakdown_test_factory(FunnelOrderType.UNORDERED),  # type: ignore
):
    maxDiff = None

    def test_funnel_step_breakdown_event_single_person_events_with_multiple_properties(self):
        # overriden from factory

        query = unordered_funnels_query(
            series=[
                EventsNode(event="sign up", name="sign up"),
                EventsNode(event="play movie", name="play movie"),
            ],
            date_from="2020-01-01",
            date_to="2020-01-08",
            breakdown="$browser",
            breakdown_attribution_type=BreakdownAttributionType.ALL_EVENTS,
            funnel_window_interval=7,
        )

        # event
        person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person1",
            properties={"key": "val", "$browser": "Chrome"},
            timestamp="2020-01-01T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person1",
            properties={"key": "val", "$browser": "Safari"},
            timestamp="2020-01-02T13:00:00Z",
        )
        _create_event(
            team=self.team,
            event="play movie",
            distinct_id="person1",
            properties={"key": "val", "$browser": "Safari"},
            timestamp="2020-01-02T14:00:00Z",
        )

        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        assert_funnel_results_equal(
            results[0],
            [
                {
                    "action_id": None,
                    "name": "Completed 1 step",
                    "custom_name": None,
                    "order": 0,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                    "breakdown": ["Safari"],
                    "breakdown_value": ["Safari"],
                },
                {
                    "action_id": None,
                    "name": "Completed 2 steps",
                    "custom_name": None,
                    "order": 1,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": 3600,
                    "median_conversion_time": 3600,
                    "breakdown": ["Safari"],
                    "breakdown_value": ["Safari"],
                },
            ],
        )
        self.assertCountEqual(self._get_actor_ids_at_step(query, 1, ["Safari"]), [person1.uuid])
        self.assertCountEqual(self._get_actor_ids_at_step(query, 2, ["Safari"]), [person1.uuid])
        assert_funnel_results_equal(
            results[1],
            [
                {
                    "action_id": None,
                    "name": "Completed 1 step",
                    "custom_name": None,
                    "order": 0,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                    "breakdown": ["Chrome"],
                    "breakdown_value": ["Chrome"],
                },
                {
                    "action_id": None,
                    "name": "Completed 2 steps",
                    "custom_name": None,
                    "order": 1,
                    "people": [],
                    "count": 0,
                    "type": "events",
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                    "breakdown": ["Chrome"],
                    "breakdown_value": ["Chrome"],
                },
            ],
        )
        self.assertCountEqual(self._get_actor_ids_at_step(query, 1, ["Chrome"]), [person1.uuid])
        self.assertCountEqual(self._get_actor_ids_at_step(query, 2, ["Chrome"]), [])

    def test_funnel_step_breakdown_with_step_attribution(self):
        # overridden from factory, since with no order, step one is step zero, and vice versa

        query = unordered_funnels_query(
            series=[
                EventsNode(event="sign up", name="sign up"),
                EventsNode(event="buy", name="buy"),
            ],
            date_from="2020-01-01",
            date_to="2020-01-08",
            breakdown=["$browser"],
            breakdown_attribution_type=BreakdownAttributionType.STEP,
            breakdown_attribution_value=0,
        )

        # event
        events_by_person = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 1, 12),
                    "properties": {"$browser": "Chrome"},
                },
                {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
            ],
            "person2": [
                {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 2, 13),
                    "properties": {"$browser": "Safari"},
                },
            ],
            "person3": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 14),
                    "properties": {"$browser": "Mac"},
                },
                {"event": "buy", "timestamp": datetime(2020, 1, 2, 15)},
            ],
            "person4": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 15),
                    "properties": {"$browser": 0},
                },
                # step attribution means alakazam is valid when step = 1
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 2, 16),
                    "properties": {"$browser": "alakazam"},
                },
            ],
        }
        people = journeys_for(events_by_person, self.team)

        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results
        results = sorted(results, key=lambda res: res[0]["breakdown"])

        self.assertEqual(len(results), 6)

        self.assertCountEqual(self._get_actor_ids_at_step(query, 1, "Mac"), [people["person3"].uuid])

    def test_funnel_step_breakdown_with_step_one_attribution(self):
        # overridden from factory, since with no order, step one is step zero, and vice versa
        query = unordered_funnels_query(
            series=[
                EventsNode(event="sign up", name="sign up"),
                EventsNode(event="buy", name="buy"),
            ],
            date_from="2020-01-01",
            date_to="2020-01-08",
            breakdown=["$browser"],
            breakdown_attribution_type=BreakdownAttributionType.STEP,
            breakdown_attribution_value=1,
        )

        # event
        events_by_person = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 1, 12),
                    "properties": {"$browser": "Chrome"},
                },
                {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
            ],
            "person2": [
                {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 2, 13),
                    "properties": {"$browser": "Safari"},
                },
            ],
            "person3": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 14),
                    "properties": {"$browser": "Mac"},
                },
                {"event": "buy", "timestamp": datetime(2020, 1, 2, 15)},
            ],
            "person4": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 15),
                    "properties": {"$browser": 0},
                },
                # step attribution means alakazam is valid when step = 1
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 2, 16),
                    "properties": {"$browser": "alakazam"},
                },
            ],
        }
        people = journeys_for(events_by_person, self.team)

        runner = FunnelsQueryRunner(query=query, team=self.team)
        if isinstance(runner.funnel_class, FunnelUDF):
            # We don't actually support non step 0 attribution in unordered funnels. Test is vestigial.
            self.assertRaises(ValidationError, runner.calculate)
            return
        results = runner.calculate().results
        results = sorted(results, key=lambda res: res[0]["breakdown"])

        self.assertEqual(len(results), 6)
        # unordered, so everything is step one too.

        self._assert_funnel_breakdown_result_is_correct(
            results[0],
            [
                FunnelStepResult(name="Completed 1 step", breakdown=[""], count=3),
                FunnelStepResult(
                    name="Completed 2 steps",
                    breakdown=[""],
                    count=2,
                    average_conversion_time=3600,
                    median_conversion_time=3600,
                ),
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(query, 1, ""),
            [people["person1"].uuid, people["person2"].uuid, people["person3"].uuid],
        )
        self.assertCountEqual(
            self._get_actor_ids_at_step(query, 2, ""),
            [people["person1"].uuid, people["person3"].uuid],
        )

        self._assert_funnel_breakdown_result_is_correct(
            results[1],
            [
                FunnelStepResult(name="Completed 1 step", breakdown=["0"], count=1),
                FunnelStepResult(name="Completed 2 steps", breakdown=["0"], count=0),
            ],
        )

        self.assertCountEqual(self._get_actor_ids_at_step(query, 1, "0"), [people["person4"].uuid])

    def test_funnel_step_breakdown_with_step_one_attribution_incomplete_funnel(self):
        # overridden from factory, since with no order, step one is step zero, and vice versa

        query = unordered_funnels_query(
            series=[
                EventsNode(event="sign up", name="sign up"),
                EventsNode(event="buy", name="buy"),
            ],
            date_from="2020-01-01",
            date_to="2020-01-08",
            breakdown=["$browser"],
            breakdown_attribution_type=BreakdownAttributionType.STEP,
            breakdown_attribution_value=1,
        )

        # event
        events_by_person = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 1, 12),
                    "properties": {"$browser": "Chrome"},
                },
                {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
            ],
            "person2": [
                {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                # {"event": "buy", "timestamp": datetime(2020, 1, 2, 13), "properties": {"$browser": "Safari"}}
            ],
            "person3": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 14),
                    "properties": {"$browser": "Mac"},
                },
                # {"event": "buy", "timestamp": datetime(2020, 1, 2, 15)}
            ],
            "person4": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 15),
                    "properties": {"$browser": 0},
                },
                # step attribution means alakazam is valid when step = 1
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 2, 16),
                    "properties": {"$browser": "alakazam"},
                },
            ],
        }
        journeys_for(events_by_person, self.team)

        runner = FunnelsQueryRunner(query=query, team=self.team)
        if isinstance(runner.funnel_class, FunnelUDF):
            # We don't actually support non step 0 attribution in unordered funnels. Test is vestigial.
            self.assertRaises(ValidationError, runner.calculate)

    def test_funnel_step_non_array_breakdown_with_step_one_attribution_incomplete_funnel(self):
        # overridden from factory, since with no order, step one is step zero, and vice versa

        query = unordered_funnels_query(
            series=[
                EventsNode(event="sign up", name="sign up"),
                EventsNode(event="buy", name="buy"),
            ],
            date_from="2020-01-01",
            date_to="2020-01-08",
            breakdown="$browser",
            breakdown_attribution_type=BreakdownAttributionType.STEP,
            breakdown_attribution_value=1,
        )

        # event
        events_by_person = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 1, 12),
                    "properties": {"$browser": "Chrome"},
                },
                {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
            ],
            "person2": [
                {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                # {"event": "buy", "timestamp": datetime(2020, 1, 2, 13), "properties": {"$browser": "Safari"}}
            ],
            "person3": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 14),
                    "properties": {"$browser": "Mac"},
                },
                # {"event": "buy", "timestamp": datetime(2020, 1, 2, 15)}
            ],
            "person4": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 15),
                    "properties": {"$browser": 0},
                },
                # step attribution means alakazam is valid when step = 1
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 2, 16),
                    "properties": {"$browser": "alakazam"},
                },
            ],
        }
        journeys_for(events_by_person, self.team)

        runner = FunnelsQueryRunner(query=query, team=self.team)
        if isinstance(runner.funnel_class, FunnelUDF):
            # We don't actually support non step 0 attribution in unordered funnels. Test is vestigial.
            self.assertRaises(ValidationError, runner.calculate)

    @snapshot_clickhouse_queries
    def test_funnel_breakdown_correct_breakdown_props_are_chosen_for_step(self):
        # No person querying here, so snapshots are more legible
        # overridden from factory, since we need to add `funnel_order_type`

        query = unordered_funnels_query(
            series=[
                EventsNode(event="sign up", name="sign up"),
                EventsNode(
                    event="buy",
                    name="buy",
                    properties=[
                        EventPropertyFilter(
                            key="$version",
                            operator=PropertyOperator.EXACT,
                            type="event",
                            value="xyz",
                        )
                    ],
                ),
            ],
            date_from="2020-01-01",
            date_to="2020-01-08",
            breakdown="$browser",
            breakdown_attribution_type=BreakdownAttributionType.STEP,
            breakdown_attribution_value=1,
        )

        # event
        events_by_person = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 1, 12),
                    "properties": {"$browser": "Chrome", "$version": "xyz"},
                },
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 1, 13),
                    "properties": {"$browser": "Chrome"},
                },
                # discarded because doesn't meet criteria
            ],
            "person2": [
                {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 2, 13),
                    "properties": {"$browser": "Safari", "$version": "xyz"},
                },
            ],
            "person3": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 14),
                    "properties": {"$browser": "Mac"},
                },
                {
                    "event": "buy",
                    "timestamp": datetime(2020, 1, 2, 15),
                    "properties": {"$version": "xyz", "$browser": "Mac"},
                },
            ],
            # no properties dude, doesn't make it to step 1, and since breakdown on step 1, is discarded completely
            "person5": [
                {"event": "sign up", "timestamp": datetime(2020, 1, 2, 15)},
                {"event": "buy", "timestamp": datetime(2020, 1, 2, 16)},
            ],
        }
        journeys_for(events_by_person, self.team)

        runner = FunnelsQueryRunner(query=query, team=self.team)
        if isinstance(runner.funnel_class, FunnelUDF):
            # We don't actually support non step 0 attribution in unordered funnels. Test is vestigial.
            self.assertRaises(ValidationError, runner.calculate)
            return

        results = runner.calculate().results
        results = sorted(results, key=lambda res: res[0]["breakdown"])

        self.assertEqual(len(results), 3)

        self.assertCountEqual([res[0]["breakdown"] for res in results], [[""], ["Mac"], ["Safari"]])


class TestFunnelUnorderedGroupBreakdown(
    ClickhouseTestMixin,
    funnel_breakdown_group_test_factory(FunnelOrderType.UNORDERED),  # type: ignore
):
    maxDiff = None


class TestFunnelUnorderedStepsConversionTime(
    ClickhouseTestMixin,
    funnel_conversion_time_test_factory(FunnelOrderType.UNORDERED),  # type: ignore
):
    maxDiff = None


class TestFunnelUnorderedSteps(ClickhouseTestMixin, APIBaseTest):
    def _get_actor_ids_at_step(self, query: FunnelsQuery, funnel_step, breakdown_value=None):
        actors = get_actors(
            query,
            self.team,
            funnel_step=funnel_step,
            funnel_step_breakdown=breakdown_value,
        )
        return [actor[0] for actor in actors]

    def test_basic_unordered_funnel(self):
        query = unordered_funnels_query(
            series=[
                EventsNode(event="user signed up", name="user signed up"),
                EventsNode(event="$pageview", name="$pageview"),
                EventsNode(event="insight viewed", name="insight viewed"),
            ]
        )

        person1_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")

        person2_stopped_after_one_pageview = _create_person(
            distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview1")
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_pageview1",
        )

        person3_stopped_after_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview",
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview")
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview",
        )

        person4_stopped_after_insight_view_reverse_order = _create_person(
            distinct_ids=["stopped_after_insightview2"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview2",
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview2")
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview2",
        )

        person5_stopped_after_insight_view_random = _create_person(
            distinct_ids=["stopped_after_insightview3"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview3")
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview3",
        )
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview3")
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview3",
        )

        person6_did_only_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview4"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview4")
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview4",
        )

        person7_did_only_pageview = _create_person(distinct_ids=["stopped_after_insightview5"], team_id=self.team.pk)
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview5")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview5")

        person8_didnot_signup = _create_person(distinct_ids=["stopped_after_insightview6"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview6",
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview6")

        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(results[0]["name"], "Completed 1 step")
        self.assertEqual(results[0]["count"], 8)
        self.assertEqual(results[1]["name"], "Completed 2 steps")
        self.assertEqual(results[1]["count"], 5)
        self.assertEqual(results[2]["name"], "Completed 3 steps")
        self.assertEqual(results[2]["count"], 3)

        self.assertCountEqual(
            self._get_actor_ids_at_step(query, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_reverse_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
                person6_did_only_insight_view.uuid,
                person7_did_only_pageview.uuid,
                person8_didnot_signup.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(query, 2),
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_reverse_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
                person8_didnot_signup.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(query, -2),
            [
                person1_stopped_after_signup.uuid,
                person6_did_only_insight_view.uuid,
                person7_did_only_pageview.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(query, 3),
            [
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_reverse_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(query, -3),
            [person2_stopped_after_one_pageview.uuid, person8_didnot_signup.uuid],
        )

    def test_big_multi_step_unordered_funnel(self):
        query = unordered_funnels_query(
            series=[
                EventsNode(event="user signed up", name="user signed up"),
                EventsNode(event="$pageview", name="$pageview"),
                EventsNode(event="insight viewed", name="insight viewed"),
                EventsNode(event="crying", name="crying"),
            ]
        )

        person1_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")

        person2_stopped_after_one_pageview = _create_person(
            distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview1")
        _create_event(team=self.team, event="crying", distinct_id="stopped_after_pageview1")

        person3_stopped_after_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview",
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview")
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview",
        )

        person4_stopped_after_insight_view_reverse_order = _create_person(
            distinct_ids=["stopped_after_insightview2"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview2",
        )
        _create_event(team=self.team, event="crying", distinct_id="stopped_after_insightview2")
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview2",
        )

        person5_stopped_after_insight_view_random = _create_person(
            distinct_ids=["stopped_after_insightview3"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview3")
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview3",
        )
        _create_event(team=self.team, event="crying", distinct_id="stopped_after_insightview3")
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview3",
        )

        person6_did_only_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview4"], team_id=self.team.pk
        )
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview4")
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview4",
        )

        person7_did_only_pageview = _create_person(distinct_ids=["stopped_after_insightview5"], team_id=self.team.pk)
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview5")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview5")

        person8_didnot_signup = _create_person(distinct_ids=["stopped_after_insightview6"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview6",
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview6")

        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(results[0]["name"], "Completed 1 step")
        self.assertEqual(results[0]["count"], 8)
        self.assertEqual(results[1]["name"], "Completed 2 steps")
        self.assertEqual(results[1]["count"], 5)
        self.assertEqual(results[2]["name"], "Completed 3 steps")
        self.assertEqual(results[2]["count"], 3)
        self.assertEqual(results[3]["name"], "Completed 4 steps")
        self.assertEqual(results[3]["count"], 1)

        self.assertCountEqual(
            self._get_actor_ids_at_step(query, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_reverse_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
                person6_did_only_insight_view.uuid,
                person7_did_only_pageview.uuid,
                person8_didnot_signup.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(query, 2),
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_reverse_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
                person8_didnot_signup.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(query, 3),
            [
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_reverse_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(query, 4),
            [person5_stopped_after_insight_view_random.uuid],
        )

    def test_basic_unordered_funnel_conversion_times(self):
        query = unordered_funnels_query(
            series=[
                EventsNode(event="user signed up", name="user signed up"),
                EventsNode(event="$pageview", name="$pageview"),
                EventsNode(event="insight viewed", name="insight viewed"),
            ],
            date_from="2021-05-01 00:00:00",
            date_to="2021-05-07 23:59:59",
            funnel_window_interval=1,
        )

        person1_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_signup1",
            timestamp="2021-05-02 00:00:00",
        )

        person2_stopped_after_one_pageview = _create_person(
            distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_pageview1",
            timestamp="2021-05-02 00:00:00",
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_pageview1",
            timestamp="2021-05-02 01:00:00",
        )

        person3_stopped_after_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-02 00:00:00",
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-02 02:00:00",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-02 04:00:00",
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-03 00:00:00",
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-03 03:00:00",
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-03 06:00:00",
        )
        # Person 3 completes the funnel 2 times:
        # First time: 2 hours + 2 hours = total 4 hours.
        # Second time: 3 hours + 3 hours = total 6 hours.

        runner = FunnelsQueryRunner(query=query, team=self.team)
        results = runner.calculate().results

        self.assertEqual(results[0]["name"], "Completed 1 step")
        self.assertEqual(results[1]["name"], "Completed 2 steps")
        self.assertEqual(results[2]["name"], "Completed 3 steps")
        self.assertEqual(results[0]["count"], 3)

        if isinstance(runner.funnel_class, FunnelUDF):
            # UDF Funnels take the first conversion, not an average of all of their conversions
            self.assertEqual(results[1]["average_conversion_time"], 5400)
            self.assertEqual(results[2]["average_conversion_time"], 7200)
        else:
            # 1 hour for Person 2, (2+3)/2 hours for Person 3, total = 3.5 hours, average = 3.5/2 = 1.75 hours
            self.assertEqual(results[1]["average_conversion_time"], 6300)
            # (2+3)/2 hours for Person 3 = 2.5 hours
            self.assertEqual(results[2]["average_conversion_time"], 9000)

        self.assertCountEqual(
            self._get_actor_ids_at_step(query, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(query, 2),
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(query, 3),
            [person3_stopped_after_insight_view.uuid],
        )

    def test_funnel_exclusions_invalid_params(self):
        query = unordered_funnels_query(
            series=[
                EventsNode(event="user signed up", name="user signed up"),
                EventsNode(event="paid", name="paid"),
                EventsNode(event="blah", name="blah"),
            ],
            exclusions=[
                FunnelExclusionEventsNode(
                    event="x",
                    funnelFromStep=1,
                    funnelToStep=1,
                    name="x",
                )
            ],
        )
        self.assertRaises(ValidationError, lambda: FunnelsQueryRunner(query=query, team=self.team).calculate())

        # partial windows not allowed for unordered
        query = unordered_funnels_query(
            series=[
                EventsNode(event="user signed up", name="user signed up"),
                EventsNode(event="paid", name="paid"),
                EventsNode(event="blah", name="blah"),
            ],
            exclusions=[
                FunnelExclusionEventsNode(
                    event="x",
                    funnelFromStep=0,
                    funnelToStep=1,
                    name="x",
                )
            ],
        )
        self.assertRaises(ValidationError, lambda: FunnelsQueryRunner(query=query, team=self.team).calculate())

    def test_funnel_exclusions_full_window(self):
        query = unordered_funnels_query(
            series=[
                EventsNode(event="user signed up", name="user signed up"),
                EventsNode(event="paid", name="paid"),
            ],
            date_from="2021-05-01 00:00:00",
            date_to="2021-05-14 00:00:00",
            exclusions=[
                FunnelExclusionEventsNode(
                    event="x",
                    funnelFromStep=0,
                    funnelToStep=1,
                    name="x",
                )
            ],
        )

        # event 1
        person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person1",
            timestamp="2021-05-01 01:00:00",
        )
        _create_event(
            team=self.team,
            event="paid",
            distinct_id="person1",
            timestamp="2021-05-01 02:00:00",
        )

        # event 2
        person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person2",
            timestamp="2021-05-01 03:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person2",
            timestamp="2021-05-01 03:30:00",
        )
        _create_event(
            team=self.team,
            event="paid",
            distinct_id="person2",
            timestamp="2021-05-01 04:00:00",
        )

        # event 3
        person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person3",
            timestamp="2021-05-01 05:00:00",
        )
        _create_event(
            team=self.team,
            event="paid",
            distinct_id="person3",
            timestamp="2021-05-01 06:00:00",
        )

        runner = FunnelsQueryRunner(query=query, team=self.team)
        results = runner.calculate().results

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["name"], "Completed 1 step")
        self.assertEqual(results[0]["count"], 3)
        self.assertCountEqual(
            self._get_actor_ids_at_step(query, 1),
            [person1.uuid, person2.uuid, person3.uuid],
        )
        self.assertEqual(results[1]["name"], "Completed 2 steps")
        self.assertEqual(results[1]["count"], 2)

        self.assertCountEqual(self._get_actor_ids_at_step(query, 2), [person1.uuid, person3.uuid])

    def test_unordered_exclusion_after_completion(self):
        query = unordered_funnels_query(
            series=[
                EventsNode(event="user signed up", name="user signed up"),
                EventsNode(event="paid", name="paid"),
                EventsNode(event="left", name="left"),
            ],
            date_from="2021-05-01 00:00:00",
            date_to="2021-05-14 00:00:00",
            exclusions=[
                FunnelExclusionEventsNode(
                    event="x",
                    funnelFromStep=0,
                    funnelToStep=2,
                    name="x",
                )
            ],
        )

        # event 1
        _create_person(distinct_ids=["person1"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person1",
            timestamp="2021-05-01 01:00:00",
        )
        _create_event(
            team=self.team,
            event="paid",
            distinct_id="person1",
            timestamp="2021-05-01 02:00:00",
        )
        _create_event(
            team=self.team,
            event="left",
            distinct_id="person1",
            timestamp="2021-05-01 03:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person1",
            timestamp="2021-05-01 04:00:00",
        )
        _create_event(
            team=self.team,
            event="left",
            distinct_id="person1",
            timestamp="2021-05-01 05:00:00",
        )

        runner = FunnelsQueryRunner(query=query, team=self.team)
        results = runner.calculate().results

        self.assertTrue(all(x["count"] == 1 for x in results))

    def test_advanced_funnel_multiple_exclusions_between_steps(self):
        query = unordered_funnels_query(
            series=[
                EventsNode(event="user signed up", name="user signed up"),
                EventsNode(event="$pageview", name="$pageview"),
                EventsNode(event="insight viewed", name="insight viewed"),
                EventsNode(event="invite teammate", name="invite teammate"),
                EventsNode(event="pageview2", name="pageview2"),
            ],
            date_from="2021-05-01 00:00:00",
            date_to="2021-05-14 00:00:00",
            exclusions=[
                FunnelExclusionEventsNode(
                    event="x",
                    funnelFromStep=0,
                    funnelToStep=4,
                    name="x",
                ),
                FunnelExclusionEventsNode(
                    event="y",
                    funnelFromStep=0,
                    funnelToStep=4,
                    name="y",
                ),
            ],
        )

        person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person1",
            timestamp="2021-05-01 01:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person1",
            timestamp="2021-05-01 02:00:00",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp="2021-05-01 03:00:00",
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="person1",
            timestamp="2021-05-01 04:00:00",
        )
        _create_event(
            team=self.team,
            event="y",
            distinct_id="person1",
            timestamp="2021-05-01 04:30:00",
        )
        _create_event(
            team=self.team,
            event="invite teammate",
            distinct_id="person1",
            timestamp="2021-05-01 05:00:00",
        )
        _create_event(
            team=self.team,
            event="pageview2",
            distinct_id="person1",
            timestamp="2021-05-01 06:00:00",
        )

        person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person2",
            timestamp="2021-05-01 01:00:00",
        )
        _create_event(
            team=self.team,
            event="y",
            distinct_id="person2",
            timestamp="2021-05-01 01:30:00",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person2",
            timestamp="2021-05-01 02:00:00",
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="person2",
            timestamp="2021-05-01 04:00:00",
        )
        _create_event(
            team=self.team,
            event="y",
            distinct_id="person2",
            timestamp="2021-05-01 04:30:00",
        )
        _create_event(
            team=self.team,
            event="invite teammate",
            distinct_id="person2",
            timestamp="2021-05-01 05:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person2",
            timestamp="2021-05-01 05:30:00",
        )
        _create_event(
            team=self.team,
            event="pageview2",
            distinct_id="person2",
            timestamp="2021-05-01 06:00:00",
        )

        person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person3",
            timestamp="2021-05-01 01:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person3",
            timestamp="2021-05-01 01:30:00",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person3",
            timestamp="2021-05-01 02:00:00",
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="person3",
            timestamp="2021-05-01 04:00:00",
        )
        _create_event(
            team=self.team,
            event="invite teammate",
            distinct_id="person3",
            timestamp="2021-05-01 05:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person3",
            timestamp="2021-05-01 05:30:00",
        )
        _create_event(
            team=self.team,
            event="pageview2",
            distinct_id="person3",
            timestamp="2021-05-01 06:00:00",
        )

        person4 = _create_person(distinct_ids=["person4"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person4",
            timestamp="2021-05-01 01:00:00",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person4",
            timestamp="2021-05-01 02:00:00",
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="person4",
            timestamp="2021-05-01 04:00:00",
        )
        _create_event(
            team=self.team,
            event="invite teammate",
            distinct_id="person4",
            timestamp="2021-05-01 05:00:00",
        )
        _create_event(
            team=self.team,
            event="pageview2",
            distinct_id="person4",
            timestamp="2021-05-01 06:00:00",
        )

        person5 = _create_person(distinct_ids=["person5"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person5",
            timestamp="2021-05-01 01:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person5",
            timestamp="2021-05-01 01:30:00",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person5",
            timestamp="2021-05-01 02:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person5",
            timestamp="2021-05-01 02:30:00",
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="person5",
            timestamp="2021-05-01 04:00:00",
        )
        _create_event(
            team=self.team,
            event="y",
            distinct_id="person5",
            timestamp="2021-05-01 04:30:00",
        )
        _create_event(
            team=self.team,
            event="invite teammate",
            distinct_id="person5",
            timestamp="2021-05-01 05:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person5",
            timestamp="2021-05-01 05:30:00",
        )
        _create_event(
            team=self.team,
            event="pageview2",
            distinct_id="person5",
            timestamp="2021-05-01 06:00:00",
        )

        runner = FunnelsQueryRunner(query=query, team=self.team)
        results = runner.calculate().results

        self.assertEqual(results[0]["name"], "Completed 1 step")

        self.assertEqual(results[0]["count"], 5)
        self.assertEqual(results[1]["count"], 2)
        self.assertEqual(results[2]["count"], 1)
        self.assertEqual(results[3]["count"], 1)
        self.assertEqual(results[4]["count"], 1)

        self.assertCountEqual(
            self._get_actor_ids_at_step(query, 1),
            [person1.uuid, person2.uuid, person3.uuid, person4.uuid, person5.uuid],
        )
        self.assertCountEqual(self._get_actor_ids_at_step(query, 2), [person1.uuid, person4.uuid])
        self.assertCountEqual(self._get_actor_ids_at_step(query, 3), [person4.uuid])
        self.assertCountEqual(self._get_actor_ids_at_step(query, 4), [person4.uuid])
        self.assertCountEqual(self._get_actor_ids_at_step(query, 5), [person4.uuid])

    def test_funnel_unordered_all_events_with_properties(self):
        _create_person(distinct_ids=["user"], team=self.team)
        _create_event(event="user signed up", distinct_id="user", team=self.team)
        _create_event(
            event="added to card",
            distinct_id="user",
            properties={"is_saved": True},
            team=self.team,
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.EVENT,
            name="is_saved",
            defaults={"property_type": "Boolean"},
        )

        query = unordered_funnels_query(
            series=[
                EventsNode(event="user signed up", name="user signed up"),
                EventsNode(
                    name="All events",
                    properties=[
                        EventPropertyFilter(
                            key="is_saved",
                            operator=PropertyOperator.EXACT,
                            type="event",
                            value=["true"],
                        )
                    ],
                ),
            ]
        )
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(results[0]["count"], 1)
        self.assertEqual(results[1]["count"], 1)

    def test_funnel_unordered_entity_filters(self):
        _create_person(distinct_ids=["user"], team=self.team)
        _create_event(
            event="user signed up",
            distinct_id="user",
            properties={"prop_a": "some value"},
            team=self.team,
        )
        _create_event(
            event="user signed up",
            distinct_id="user",
            properties={"prop_b": "another value"},
            team=self.team,
        )

        query = unordered_funnels_query(
            series=[
                EventsNode(
                    event="user signed up",
                    name="user signed up",
                    properties=[
                        EventPropertyFilter(
                            key="prop_a",
                            operator=PropertyOperator.EXACT,
                            type="event",
                            value=["some value"],
                        )
                    ],
                ),
                EventsNode(
                    event="user signed up",
                    name="user signed up",
                    properties=[
                        EventPropertyFilter(
                            key="prop_b",
                            operator=PropertyOperator.ICONTAINS,
                            type="event",
                            value="another",
                        )
                    ],
                ),
            ]
        )
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(results[0]["count"], 1)
        self.assertEqual(results[1]["count"], 1)

    def test_funnel_window_ignores_dst_transition(self):
        _create_person(
            distinct_ids=[f"user_1"],
            team=self.team,
        )

        events_by_person = {
            "user_1": [
                {
                    "event": "$pageview",
                    "timestamp": datetime(2024, 3, 1, 15, 10),  # 1st March 15:10
                },
                {
                    "event": "user signed up",
                    "timestamp": datetime(
                        2024, 3, 15, 14, 27
                    ),  # 15th March 14:27 (within 14 day conversion window that ends at 15:10)
                },
            ],
        }
        journeys_for(events_by_person, self.team)

        query = unordered_funnels_query(
            series=[
                EventsNode(event="$pageview", name="$pageview"),
                EventsNode(event="user signed up", name="user signed up"),
            ],
            date_from="2024-02-17",
            date_to="2024-03-18",
        )
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(results[1]["name"], "Completed 2 steps")
        self.assertEqual(results[1]["count"], 1)
        self.assertEqual(results[1]["average_conversion_time"], 1_207_020)
        self.assertEqual(results[1]["median_conversion_time"], 1_207_020)

        # there is a PST -> PDT transition on 10th of March
        self.team.timezone = "US/Pacific"
        self.team.save()

        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        # we still should have the user here, as the conversion window should not be affected by DST
        self.assertEqual(results[1]["name"], "Completed 2 steps")
        self.assertEqual(results[1]["count"], 1)
        self.assertEqual(results[1]["average_conversion_time"], 1_207_020)
        self.assertEqual(results[1]["median_conversion_time"], 1_207_020)

    def test_unordered_trend_with_partial_steps_and_exclusion(self):
        # Test unordered_trend with partial steps (up to step 2) in a 3-step funnel with exclusion

        # Person 1: step 1 -> step 2 -> exclusion -> step 3
        # Person 2: step 1 -> step 2 -> step 3
        events_by_person = {
            "user_1": [
                {
                    "event": "step 1",
                    "timestamp": datetime(2024, 3, 1, 10, 0),
                },
                {
                    "event": "step 2",
                    "timestamp": datetime(2024, 3, 1, 11, 0),
                },
                {
                    "event": "exclusion event",
                    "timestamp": datetime(2024, 3, 1, 12, 0),
                },
                {
                    "event": "step 3",
                    "timestamp": datetime(2024, 3, 1, 13, 0),
                },
            ],
            "user_2": [
                {
                    "event": "step 1",
                    "timestamp": datetime(2024, 3, 1, 10, 0),
                },
                {
                    "event": "step 2",
                    "timestamp": datetime(2024, 3, 1, 11, 0),
                },
                {
                    "event": "step 3",
                    "timestamp": datetime(2024, 3, 1, 12, 0),
                },
            ],
        }
        journeys_for(events_by_person, self.team)

        # Define a 3-step funnel with exclusion
        full_query = unordered_funnels_query(
            series=[
                EventsNode(event="step 1", name="step 1"),
                EventsNode(event="step 2", name="step 2"),
                EventsNode(event="step 3", name="step 3"),
            ],
            date_from="2024-03-01",
            date_to="2024-03-01",
            exclusions=[
                FunnelExclusionEventsNode(
                    event="exclusion event",
                    funnelFromStep=0,
                    funnelToStep=2,
                    name="exclusion event",
                )
            ],
            funnel_window_interval=6,
            funnel_window_interval_unit=FunnelConversionWindowTimeUnit.HOUR,
        )
        full_results = FunnelsQueryRunner(query=full_query, team=self.team).calculate().results

        # User 1 should be excluded, only user 2 completes all steps
        self.assertEqual(full_results[0]["count"], 2)  # Step 1: both users
        self.assertEqual(full_results[1]["count"], 1)  # Step 2: only user 2 (user 1 excluded)
        self.assertEqual(full_results[2]["count"], 1)  # Step 3: only user 2 (user 1 excluded)

        # Now run with unordered_trend requesting only up to step 2
        trend_query = unordered_funnels_query(
            series=[
                EventsNode(event="step 1", name="step 1"),
                EventsNode(event="step 2", name="step 2"),
                EventsNode(event="step 3", name="step 3"),
            ],
            date_from="2024-03-01",
            date_to="2024-03-01",
            exclusions=[
                FunnelExclusionEventsNode(
                    event="exclusion event",
                    funnelFromStep=0,
                    funnelToStep=2,
                    name="exclusion event",
                )
            ],
            funnel_to_step=1,
            funnel_viz_type=FunnelVizType.TRENDS,
            funnel_window_interval=6,
            funnel_window_interval_unit=FunnelConversionWindowTimeUnit.HOUR,
        )
        trend_results = FunnelsQueryRunner(query=trend_query, team=self.team).calculate().results

        # Only the second user gets to step 2, after the exclusion
        self.assertEqual(len(trend_results), 1)  # One day of data
        self.assertEqual(trend_results[0]["count"], 1)
        self.assertEqual(trend_results[0]["data"], [50.0])  # Only one user completes step 2

    def test_unordered_trend(self):
        # Test unordered trend with 5 users doing event 3 with different frequencies
        # User 1: does event 3 all 8 days
        # User 2: does event 3 4 of the 8 days
        # User 3: does event 3 2 of the 8 days
        # User 4: does event 3 1 of the 8 days
        # User 5: never does event 3
        # All users do events 1 and 2 once at the end of the funnel window

        start_date = datetime(2024, 3, 1, 10, 0)

        _create_person(distinct_ids=["user_1"], team_id=self.team.pk)
        _create_person(distinct_ids=["user_2"], team_id=self.team.pk)
        _create_person(distinct_ids=["user_3"], team_id=self.team.pk)
        _create_person(distinct_ids=["user_4"], team_id=self.team.pk)
        _create_person(distinct_ids=["user_5"], team_id=self.team.pk)

        # User 1: does event 3 all 8 days
        for i in range(8):
            _create_event(
                team=self.team,
                event="event 3",
                distinct_id="user_1",
                timestamp=start_date + timedelta(days=i),
            )

        # User 2: does event 3 4 of the 8 days (days 0, 2, 4, 6)
        for i in range(0, 8, 2):
            _create_event(
                team=self.team,
                event="event 3",
                distinct_id="user_2",
                timestamp=start_date + timedelta(days=i),
            )

        # User 3: does event 3 2 of the 8 days (days 0, 4)
        for i in range(0, 8, 4):
            _create_event(
                team=self.team,
                event="event 3",
                distinct_id="user_3",
                timestamp=start_date + timedelta(days=i),
            )

        # User 4: does event 3 1 of the 8 days (day 0)
        _create_event(
            team=self.team,
            event="event 3",
            distinct_id="user_4",
            timestamp=start_date,
        )

        # All users do events 1 and 2 once at the end of the funnel window (day 7)
        for user_id in ["user_1", "user_2", "user_3", "user_4", "user_5"]:
            _create_event(
                team=self.team,
                event="event 1",
                distinct_id=user_id,
                timestamp=start_date + timedelta(days=7, hours=1),
            )
            _create_event(
                team=self.team,
                event="event 2",
                distinct_id=user_id,
                timestamp=start_date + timedelta(days=7, hours=2),
            )

        # Define a 3-step funnel with unordered events
        query = unordered_funnels_query(
            series=[
                EventsNode(event="event 1", name="event 1"),
                EventsNode(event="event 2", name="event 2"),
                EventsNode(event="event 3", name="event 3"),
            ],
            date_from="2024-03-01",
            date_to="2024-03-08",
            funnel_viz_type=FunnelVizType.TRENDS,
            funnel_window_interval=8,
        )
        trend_results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        # We should get 8 days of results
        self.assertEqual(len(trend_results), 8)

        # Day 0 (2024-03-01): 4 users do event 3, all 5 users will do events 1 and 2
        # So conversion is 4/5 = 80%
        self.assertEqual(trend_results[0]["timestamp"].strftime("%Y-%m-%d"), "2024-03-01")
        self.assertEqual(trend_results[0]["reached_from_step_count"], 4)
        self.assertEqual(trend_results[0]["reached_to_step_count"], 4)
        self.assertEqual(trend_results[0]["conversion_rate"], 100)

        # Day 1 (2024-03-02): User 1 does event 3, all 5 users will do events 1 and 2
        self.assertEqual(trend_results[1]["timestamp"].strftime("%Y-%m-%d"), "2024-03-02")
        self.assertEqual(trend_results[1]["reached_from_step_count"], 1)
        self.assertEqual(trend_results[1]["reached_to_step_count"], 1)
        self.assertEqual(trend_results[1]["conversion_rate"], 100)

        # Day 2 (2024-03-03): User 1 and User 2 do event 3, all 5 users will do events 1 and 2
        self.assertEqual(trend_results[2]["timestamp"].strftime("%Y-%m-%d"), "2024-03-03")
        self.assertEqual(trend_results[2]["reached_from_step_count"], 2)
        self.assertEqual(trend_results[2]["reached_to_step_count"], 2)
        self.assertEqual(trend_results[2]["conversion_rate"], 100)

        # Day 3 (2024-03-04): User 1 does event 3, all 5 users will do events 1 and 2
        self.assertEqual(trend_results[3]["timestamp"].strftime("%Y-%m-%d"), "2024-03-04")
        self.assertEqual(trend_results[3]["reached_from_step_count"], 1)
        self.assertEqual(trend_results[3]["reached_to_step_count"], 1)
        self.assertEqual(trend_results[3]["conversion_rate"], 100)

        # Day 4 (2024-03-05): Users 1, 2, and 3 do event 3, all 5 users will do events 1 and 2
        self.assertEqual(trend_results[4]["timestamp"].strftime("%Y-%m-%d"), "2024-03-05")
        self.assertEqual(trend_results[4]["reached_from_step_count"], 3)
        self.assertEqual(trend_results[4]["reached_to_step_count"], 3)
        self.assertEqual(trend_results[4]["conversion_rate"], 100)

        # Day 5 (2024-03-06): User 1 does event 3, all 5 users will do events 1 and 2
        self.assertEqual(trend_results[5]["timestamp"].strftime("%Y-%m-%d"), "2024-03-06")
        self.assertEqual(trend_results[5]["reached_from_step_count"], 1)
        self.assertEqual(trend_results[5]["reached_to_step_count"], 1)
        self.assertEqual(trend_results[5]["conversion_rate"], 100)

        # Day 6 (2024-03-07): Users 1 and 2 do event 3, all 5 users will do events 1 and 2
        self.assertEqual(trend_results[6]["timestamp"].strftime("%Y-%m-%d"), "2024-03-07")
        self.assertEqual(trend_results[6]["reached_from_step_count"], 2)
        self.assertEqual(trend_results[6]["reached_to_step_count"], 2)
        self.assertEqual(trend_results[6]["conversion_rate"], 100)

        # Day 7 (2024-03-08): User 1 does event 3, all 5 users do events 1 and 2
        self.assertEqual(trend_results[7]["timestamp"].strftime("%Y-%m-%d"), "2024-03-08")
        self.assertEqual(trend_results[7]["reached_from_step_count"], 5)
        self.assertEqual(trend_results[7]["reached_to_step_count"], 1)
        self.assertEqual(trend_results[7]["conversion_rate"], 20)

    def test_unordered_trend_second_step(self):
        # Test unordered trend not starting at the first step

        start_date = datetime(2024, 3, 1, 10, 0)

        _create_person(distinct_ids=["user_1"], team_id=self.team.pk)
        _create_person(distinct_ids=["user_2"], team_id=self.team.pk)

        # Both users do event 3 all 8 days
        # Both users do events 1 once at the end of the funnel window (day 7)
        for distinct_id in ("user_1", "user_2"):
            for i in range(8):
                _create_event(
                    team=self.team,
                    event="event 3",
                    distinct_id=distinct_id,
                    timestamp=start_date + timedelta(days=i),
                )
            _create_event(
                team=self.team,
                event="event 1",
                distinct_id=distinct_id,
                timestamp=start_date + timedelta(days=7, hours=1),
            )
        # User 2 does event 2 once on the last day
        _create_event(
            team=self.team,
            event="event 2",
            distinct_id="user_2",
            timestamp=start_date + timedelta(days=7, hours=2),
        )

        # Define a 3-step funnel with unordered events
        query = unordered_funnels_query(
            series=[
                EventsNode(event="event 1", name="event 1"),
                EventsNode(event="event 2", name="event 2"),
                EventsNode(event="event 3", name="event 3"),
            ],
            date_from="2024-03-01",
            date_to="2024-03-08",
            funnel_from_step=1,
            funnel_to_step=2,
            funnel_viz_type=FunnelVizType.TRENDS,
            funnel_window_interval=8,
        )
        trend_results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        # We should get 8 days of results
        self.assertEqual(len(trend_results), 8)

        for trend_result in trend_results:
            self.assertEqual(trend_result["reached_from_step_count"], 2)
            self.assertEqual(trend_result["reached_to_step_count"], 1)
            self.assertEqual(trend_result["conversion_rate"], 50)

    def test_unordered_trend_one_user(self):
        start_date = datetime(2024, 12, 1, 10, 0)
        _create_person(distinct_ids=["user_1"], team_id=self.team.pk)
        # User 1: does event 3 all 8
        for i in range(8):
            _create_event(
                team=self.team,
                event="event 3",
                distinct_id="user_1",
                timestamp=start_date + timedelta(days=i),
            )
        # User 1: does event 2 for the first 4
        for i in range(4):
            _create_event(
                team=self.team,
                event="event 2",
                distinct_id="user_1",
                timestamp=start_date + timedelta(days=i, hours=1),
            )
        # User 1: does event 1 for the first two days
        for i in range(2):
            _create_event(
                team=self.team,
                event="event 1",
                distinct_id="user_1",
                timestamp=start_date + timedelta(days=i, hours=2),
            )

        query = unordered_funnels_query(
            series=[
                EventsNode(event="event 1", name="event 1"),
                EventsNode(event="event 2", name="event 2"),
                EventsNode(event="event 3", name="event 3"),
            ],
            date_from="2024-12-01",
            date_to="2024-12-08",
            funnel_from_step=1,
            funnel_to_step=2,
            funnel_viz_type=FunnelVizType.TRENDS,
        )
        trend_results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results
        assert [x["reached_from_step_count"] for x in trend_results] == [1, 1, 1, 1, 0, 0, 0, 0]
        assert [x["reached_to_step_count"] for x in trend_results] == [1, 1, 0, 0, 0, 0, 0, 0]

    def test_unordered_trend_weekly_monthly(self):
        start_date = datetime(2024, 12, 1, 10, 0)

        _create_person(distinct_ids=["user_1"], team_id=self.team.pk)
        _create_person(distinct_ids=["user_2"], team_id=self.team.pk)
        _create_person(distinct_ids=["user_3"], team_id=self.team.pk)
        _create_person(distinct_ids=["user_4"], team_id=self.team.pk)
        _create_person(distinct_ids=["user_5"], team_id=self.team.pk)

        # User 1: does event 3 all 31 days
        for i in range(31):
            _create_event(
                team=self.team,
                event="event 3",
                distinct_id="user_1",
                timestamp=start_date + timedelta(days=i),
            )

        # User 2: does event 3 3 days a week
        for i in range(0, 31, 7):
            for j in range(0, 7, 3):
                _create_event(
                    team=self.team,
                    event="event 3",
                    distinct_id="user_2",
                    timestamp=start_date + timedelta(days=i + j),
                )

        # User 3: does event 3 2 days a week
        for i in range(0, 31, 7):
            for j in range(0, 7, 4):
                _create_event(
                    team=self.team,
                    event="event 3",
                    distinct_id="user_3",
                    timestamp=start_date + timedelta(days=i + j),
                )

        # User 4: does event 3 weekly
        for i in range(0, 31, 7):
            _create_event(
                team=self.team,
                event="event 3",
                distinct_id="user_4",
                timestamp=start_date + timedelta(days=i),
            )

        # User 5: does event 3 every other week
        for i in range(0, 31, 14):
            _create_event(
                team=self.team,
                event="event 3",
                distinct_id="user_5",
                timestamp=start_date + timedelta(days=i),
            )

        # All users do events 1 and 2 once at the end of the funnel window (day 30)
        for user_id in ["user_1", "user_2", "user_3", "user_4", "user_5"]:
            _create_event(
                team=self.team,
                event="event 1",
                distinct_id=user_id,
                timestamp=start_date + timedelta(days=30, hours=1),
            )
            _create_event(
                team=self.team,
                event="event 2",
                distinct_id=user_id,
                timestamp=start_date + timedelta(days=30, hours=2),
            )

        # Define a 3-step funnel with unordered events
        base_query = unordered_funnels_query(
            series=[
                EventsNode(event="event 1", name="event 1"),
                EventsNode(event="event 2", name="event 2"),
                EventsNode(event="event 3", name="event 3"),
            ],
            date_from="2024-12-01",
            date_to="2024-12-31",
            funnel_viz_type=FunnelVizType.TRENDS,
            funnel_window_interval=40,
        )
        query = base_query.model_copy(update={"interval": IntervalType.MONTH})
        trend_results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(trend_results[0]["reached_from_step_count"], 5)
        self.assertEqual(trend_results[0]["reached_to_step_count"], 5)

        query = base_query.model_copy(update={"interval": IntervalType.WEEK})
        trend_results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(len(trend_results), 5)

        self.assertEqual(trend_results[0]["timestamp"].strftime("%Y-%m-%d"), "2024-12-01")
        self.assertEqual(trend_results[0]["reached_from_step_count"], 5)
        self.assertEqual(trend_results[0]["reached_to_step_count"], 5)

        self.assertEqual(trend_results[1]["timestamp"].strftime("%Y-%m-%d"), "2024-12-08")
        self.assertEqual(trend_results[1]["reached_from_step_count"], 4)
        self.assertEqual(trend_results[1]["reached_to_step_count"], 4)

        self.assertEqual(trend_results[2]["timestamp"].strftime("%Y-%m-%d"), "2024-12-15")
        self.assertEqual(trend_results[2]["reached_from_step_count"], 5)
        self.assertEqual(trend_results[2]["reached_to_step_count"], 5)

        self.assertEqual(trend_results[3]["timestamp"].strftime("%Y-%m-%d"), "2024-12-22")
        self.assertEqual(trend_results[3]["reached_from_step_count"], 4)
        self.assertEqual(trend_results[3]["reached_to_step_count"], 4)

        self.assertEqual(trend_results[4]["timestamp"].strftime("%Y-%m-%d"), "2024-12-29")
        self.assertEqual(trend_results[4]["reached_from_step_count"], 5)
        self.assertEqual(trend_results[4]["reached_to_step_count"], 5)
