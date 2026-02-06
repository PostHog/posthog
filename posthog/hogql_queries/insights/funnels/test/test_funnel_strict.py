from datetime import datetime
from typing import cast

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_action, _create_event, _create_person

from posthog.schema import BreakdownAttributionType, BreakdownFilter, EventsNode, FunnelsFilter, FunnelsQuery

from posthog.hogql.constants import MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY, HogQLGlobalSettings
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query

from posthog.constants import INSIGHT_FUNNELS, FunnelOrderType
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.funnels.test.breakdown_cases import (
    assert_funnel_results_equal,
    funnel_breakdown_group_test_factory,
    funnel_breakdown_test_factory,
)
from posthog.hogql_queries.insights.funnels.test.conversion_time_cases import funnel_conversion_time_test_factory
from posthog.hogql_queries.insights.funnels.test.test_funnel_persons import get_actors_legacy_filters
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.models.instance_setting import override_instance_config
from posthog.test.test_journeys import journeys_for

FORMAT_TIME = "%Y-%m-%d 00:00:00"


class TestFunnelStrictStepsBreakdown(
    ClickhouseTestMixin,
    funnel_breakdown_test_factory(FunnelOrderType.STRICT),  # type: ignore
):
    maxDiff = None

    def test_basic_funnel_default_funnel_days_breakdown_event(self):
        # TODO: This test and the one below it fail, only for strict funnels. Figure out why and how to fix
        pass

    def test_basic_funnel_default_funnel_days_breakdown_action(self):
        pass

    def test_basic_funnel_default_funnel_days_breakdown_action_materialized(self):
        pass

    def test_strict_breakdown_events_with_multiple_properties(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
            "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}],
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
            "breakdown_type": "event",
            "breakdown": "$browser",
        }

        people = journeys_for(
            {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "blah",
                        "timestamp": datetime(2020, 1, 1, 13),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 1, 14),
                        "properties": {"$browser": "Chrome"},
                    },
                ],
                "person2": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 13),
                        "properties": {"$browser": "Safari"},
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Safari"},
                    },
                ],
            },
            self.team,
        )

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        assert_funnel_results_equal(
            results[0],
            [
                {
                    "action_id": "sign up",
                    "name": "sign up",
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
                    "action_id": "play movie",
                    "name": "play movie",
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
        self.assertCountEqual(self._get_actor_ids_at_step(filters, 1, ["Safari"]), [people["person2"].uuid])
        self.assertCountEqual(self._get_actor_ids_at_step(filters, 2, ["Safari"]), [people["person2"].uuid])

        assert_funnel_results_equal(
            results[1],
            [
                {
                    "action_id": "sign up",
                    "name": "sign up",
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
                    "action_id": "play movie",
                    "name": "play movie",
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
        self.assertCountEqual(self._get_actor_ids_at_step(filters, 1, ["Chrome"]), [people["person1"].uuid])
        self.assertCountEqual(self._get_actor_ids_at_step(filters, 2, ["Chrome"]), [])


class TestStrictFunnelGroupBreakdown(
    ClickhouseTestMixin,
    funnel_breakdown_group_test_factory(FunnelOrderType.STRICT),  # type: ignore
):
    maxDiff = None


class TestFunnelStrictStepsConversionTime(
    ClickhouseTestMixin,
    funnel_conversion_time_test_factory(FunnelOrderType.ORDERED),  # type: ignore
):
    maxDiff = None


class TestFunnelStrictSteps(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _get_actor_ids_at_step(self, filter, funnel_step, breakdown_value=None):
        actors = get_actors_legacy_filters(
            filter,
            self.team,
            funnel_step=funnel_step,
            funnel_step_breakdown=breakdown_value,
        )
        return [actor[0] for actor in actors]

    def test_basic_strict_funnel(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
            "events": [
                {"id": "user signed up", "order": 0},
                {"id": "$pageview", "order": 1},
                {"id": "insight viewed", "order": 2},
            ],
        }

        person1_stopped_after_signup = _create_person(
            distinct_ids=["stopped_after_signup1"],
            team_id=self.team.pk,
            properties={"test": "okay"},
        )
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

        person4_stopped_after_insight_view_not_strict_order = _create_person(
            distinct_ids=["stopped_after_insightview2"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview2",
        )
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview2")
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
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview3")
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview3",
        )

        person6 = _create_person(distinct_ids=["person6"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person6")
        _create_event(team=self.team, event="user signed up", distinct_id="person6")
        _create_event(team=self.team, event="blaah blaa", distinct_id="person6")
        _create_event(team=self.team, event="$pageview", distinct_id="person6")

        person7 = _create_person(distinct_ids=["person7"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person7")
        _create_event(team=self.team, event="user signed up", distinct_id="person7")
        _create_event(team=self.team, event="$pageview", distinct_id="person7")
        _create_event(team=self.team, event="insight viewed", distinct_id="person7")
        _create_event(team=self.team, event="blaah blaa", distinct_id="person7")

        _create_person(distinct_ids=["stopped_after_insightview6"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview6",
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview6")

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(results[0]["name"], "user signed up")
        self.assertEqual(results[1]["name"], "$pageview")
        self.assertEqual(results[2]["name"], "insight viewed")
        self.assertEqual(results[0]["count"], 7)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filters, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
                person4_stopped_after_insight_view_not_strict_order.uuid,
                person5_stopped_after_insight_view_random.uuid,
                person6.uuid,
                person7.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filters, 2),
            [person3_stopped_after_insight_view.uuid, person7.uuid],
        )

        self.assertCountEqual(self._get_actor_ids_at_step(filters, 3), [person7.uuid])

        with override_instance_config("AGGREGATE_BY_DISTINCT_IDS_TEAMS", f"{self.team.pk}"):
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results
            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[1]["name"], "$pageview")
            self.assertEqual(results[2]["name"], "insight viewed")
            self.assertEqual(results[0]["count"], 7)

    def test_advanced_strict_funnel(self):
        sign_up_action = _create_action(
            name="sign up",
            team=self.team,
            properties=[{"key": "key", "type": "event", "value": ["val"], "operator": "exact"}],
        )

        view_action = _create_action(
            name="pageview",
            team=self.team,
            properties=[{"key": "key", "type": "event", "value": ["val"], "operator": "exact"}],
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "$pageview", "type": "events", "order": 2},
            ],
            "actions": [
                {"id": sign_up_action.id, "math": "dau", "order": 1},
                {"id": view_action.id, "math": "weekly_active", "order": 3},
            ],
        }

        person1_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
        _create_event(team=self.team, event="user signed up", distinct_id="stopped_after_signup1")

        person2_stopped_after_one_pageview = _create_person(
            distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_pageview1",
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview1")

        person3_stopped_after_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview",
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="stopped_after_insightview",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="stopped_after_insightview",
            properties={"key": "val2"},
        )
        _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_insightview")
        _create_event(team=self.team, event="blaah blaa", distinct_id="stopped_after_insightview")
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview",
        )

        person4 = _create_person(distinct_ids=["person4"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person4")
        _create_event(team=self.team, event="user signed up", distinct_id="person4")
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person4",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person4",
            properties={"key": "val"},
        )
        _create_event(team=self.team, event="blaah blaa", distinct_id="person4")

        person5 = _create_person(distinct_ids=["person5"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person5")
        _create_event(team=self.team, event="user signed up", distinct_id="person5")
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person5",
            properties={"key": "val"},
        )
        _create_event(team=self.team, event="$pageview", distinct_id="person5")
        _create_event(team=self.team, event="blaah blaa", distinct_id="person5")

        person6 = _create_person(distinct_ids=["person6"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person6")
        _create_event(team=self.team, event="user signed up", distinct_id="person6")
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person6",
            properties={"key": "val"},
        )
        _create_event(team=self.team, event="$pageview", distinct_id="person6")
        _create_event(
            team=self.team,
            event="pageview",
            distinct_id="person6",
            properties={"key": "val1"},
        )

        person7 = _create_person(distinct_ids=["person7"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person7")
        _create_event(team=self.team, event="user signed up", distinct_id="person7")
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person7",
            properties={"key": "val"},
        )
        _create_event(team=self.team, event="$pageview", distinct_id="person7")
        _create_event(team=self.team, event="user signed up", distinct_id="person7")
        _create_event(
            team=self.team,
            event="pageview",
            distinct_id="person7",
            properties={"key": "val"},
        )

        person8 = _create_person(distinct_ids=["person8"], team_id=self.team.pk)
        _create_event(team=self.team, event="blaah blaa", distinct_id="person8")
        _create_event(team=self.team, event="user signed up", distinct_id="person8")
        _create_event(team=self.team, event="user signed up", distinct_id="person8")
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person8",
            properties={"key": "val"},
        )
        _create_event(team=self.team, event="$pageview", distinct_id="person8")
        _create_event(
            team=self.team,
            event="pageview",
            distinct_id="person8",
            properties={"key": "val"},
        )

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(results[0]["name"], "user signed up")
        self.assertEqual(results[1]["name"], "sign up")
        self.assertEqual(results[2]["name"], "$pageview")
        self.assertEqual(results[3]["name"], "pageview")
        self.assertEqual(results[0]["count"], 8)

        self.assertCountEqual(
            self._get_actor_ids_at_step(filters, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
                person4.uuid,
                person5.uuid,
                person6.uuid,
                person7.uuid,
                person8.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filters, 2),
            [
                person3_stopped_after_insight_view.uuid,
                person4.uuid,
                person5.uuid,
                person6.uuid,
                person7.uuid,
                person8.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filters, 3),
            [person4.uuid, person5.uuid, person6.uuid, person7.uuid, person8.uuid],
        )

        self.assertCountEqual(self._get_actor_ids_at_step(filters, 4), [person8.uuid])

    def test_basic_strict_funnel_conversion_times(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
            "events": [
                {"id": "user signed up", "order": 0},
                {"id": "$pageview", "order": 1},
                {"id": "insight viewed", "order": 2},
            ],
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 23:59:59",
        }

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
            event="user signed up",
            distinct_id="stopped_after_pageview1",
            timestamp="2021-05-02 00:00:00",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_pageview1",
            timestamp="2021-05-02 01:00:00",
        )

        person3_stopped_after_insight_view = _create_person(
            distinct_ids=["stopped_after_insightview"], team_id=self.team.pk
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-02 00:00:00",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-02 02:00:00",
        )
        _create_event(
            team=self.team,
            event="insight viewed",
            distinct_id="stopped_after_insightview",
            timestamp="2021-05-02 04:00:00",
        )

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(results[0]["name"], "user signed up")
        self.assertEqual(results[1]["name"], "$pageview")
        self.assertEqual(results[2]["name"], "insight viewed")
        self.assertEqual(results[0]["count"], 3)

        self.assertEqual(results[1]["average_conversion_time"], 5400)
        # 1 hour for Person 2, 2 hours for Person 3, average = 1.5 hours

        self.assertEqual(results[2]["average_conversion_time"], 7200)
        # 2 hours for Person 3

        self.assertCountEqual(
            self._get_actor_ids_at_step(filters, 1),
            [
                person1_stopped_after_signup.uuid,
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filters, 2),
            [
                person2_stopped_after_one_pageview.uuid,
                person3_stopped_after_insight_view.uuid,
            ],
        )

        self.assertCountEqual(
            self._get_actor_ids_at_step(filters, 3),
            [person3_stopped_after_insight_view.uuid],
        )

    def test_redundant_event_filtering_strict_funnel(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
            "events": [
                {"id": "$pageview", "order": 1},
                {"id": "insight viewed", "order": 2},
            ],
        }

        _create_person(
            distinct_ids=["many_other_events"],
            team_id=self.team.pk,
            properties={"test": "okay"},
        )
        for _ in range(10):
            _create_event(team=self.team, event="user signed up", distinct_id="many_other_events")

        query = cast(FunnelsQuery, filter_to_query(filters))
        runner = FunnelsQueryRunner(query=query, team=self.team)
        inner_aggregation_query = runner.funnel_class._inner_aggregation_query()
        inner_aggregation_query.select.append(
            parse_expr(f"{runner.funnel_class.event_array_filter()} AS filtered_array")
        )
        inner_aggregation_query.having = None
        response = execute_hogql_query(
            query_type="FunnelsQuery",
            query=inner_aggregation_query,
            team=self.team,
            settings=HogQLGlobalSettings(
                # Make sure funnel queries never OOM
                max_bytes_before_external_group_by=MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY,
                allow_experimental_analyzer=True,
            ),
        )
        # Make sure the events have been condensed down to two
        self.assertEqual(2, len(response.results[0][-1]))

    def test_different_prop_val_in_strict_filter(self):
        funnels_query = FunnelsQuery(
            series=[EventsNode(event="first"), EventsNode(event="second")],
            breakdownFilter=BreakdownFilter(breakdown="bd"),
            funnelsFilter=FunnelsFilter(funnelOrderType=FunnelOrderType.STRICT),
        )

        _create_person(
            distinct_ids=["many_other_events"],
            team_id=self.team.pk,
            properties={"test": "okay"},
        )
        _create_event(team=self.team, event="first", distinct_id="many_other_events", properties={"bd": "one"})
        _create_event(team=self.team, event="first", distinct_id="many_other_events", properties={"bd": "two"})
        _create_event(team=self.team, event="unmatched", distinct_id="many_other_events", properties={"bd": "one"})
        _create_event(team=self.team, event="unmatched", distinct_id="many_other_events", properties={"bd": "two"})
        _create_event(team=self.team, event="second", distinct_id="many_other_events", properties={"bd": "one"})
        _create_event(team=self.team, event="second", distinct_id="many_other_events", properties={"bd": "two"})

        # First Touchpoint (just "one")
        results = FunnelsQueryRunner(query=funnels_query, team=self.team).calculate().results

        assert 2 == len(results[0])
        assert results[0][-1]["count"] == 0
        assert all(result["breakdown"] == ["one"] for result in results[0])

        # All events attribution
        assert funnels_query.funnelsFilter is not None
        funnels_query.funnelsFilter.breakdownAttributionType = BreakdownAttributionType.ALL_EVENTS
        results = FunnelsQueryRunner(query=funnels_query, team=self.team).calculate().results

        assert 2 == len(results)
        one = next(x for x in results if x[0]["breakdown"] == ["one"])
        assert one[-1]["count"] == 0
        two = next(x for x in results if x[0]["breakdown"] == ["two"])
        assert two[-1]["count"] == 0

    def test_multiple_events_same_timestamp_doesnt_blow_up(self):
        _create_person(distinct_ids=["test"], team_id=self.team.pk)
        with freeze_time("2024-01-10T12:01:00"):
            for _ in range(30):
                _create_event(team=self.team, event="step one", distinct_id="test")
            _create_event(team=self.team, event="step two", distinct_id="test")
            _create_event(team=self.team, event="step three", distinct_id="test")
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "steps",
            "date_from": "2024-01-10 00:00:00",
            "date_to": "2024-01-12 00:00:00",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results
        self.assertEqual(1, results[-1]["count"])
