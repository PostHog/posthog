import json
import uuid
import dataclasses
from datetime import datetime
from typing import Any, Optional, Union, cast
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_different_timezones,
    also_test_with_materialized_columns,
    also_test_with_person_on_events_v2,
    create_person_id_override_by_distinct_id,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActionsNode,
    BreakdownFilter,
    CompareFilter,
    DataWarehouseNode,
    DateRange,
    EventsNode,
    PropertyGroupFilter,
    TrendsFilter,
    TrendsQuery,
)

from posthog.constants import TREND_FILTER_TYPE_EVENTS, TRENDS_BAR_VALUE, TRENDS_LINEAR, TRENDS_TABLE
from posthog.hogql_queries.insights.trends.test.test_trends_persons import get_actors
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.legacy_compatibility.filter_to_query import (
    clean_entity_properties,
    clean_global_properties,
    filter_to_query,
)
from posthog.models import Action, Cohort, Entity, Filter, Organization, Person
from posthog.models.group.util import create_group
from posthog.models.instance_setting import get_instance_setting, override_instance_config
from posthog.models.person.util import create_person_distinct_id
from posthog.models.property_definition import PropertyDefinition
from posthog.models.team.team import Team
from posthog.models.utils import uuid7
from posthog.test.test_journeys import journeys_for
from posthog.test.test_utils import create_group_type_mapping_without_created_at


def breakdown_label(entity: Entity, value: Union[str, int]) -> dict[str, Optional[Union[str, int]]]:
    ret_dict: dict[str, Optional[Union[str, int]]] = {}
    if not value or not isinstance(value, str) or "cohort_" not in value:
        label = value if (value or isinstance(value, bool)) and value != "None" and value != "nan" else "Other"
        ret_dict["label"] = f"{entity.name} - {label}"
        ret_dict["breakdown_value"] = label
    else:
        if value == "cohort_all":
            ret_dict["label"] = f"{entity.name} - all users"
            ret_dict["breakdown_value"] = "all"
        else:
            cohort = Cohort.objects.get(pk=value.replace("cohort_", ""))
            ret_dict["label"] = f"{entity.name} - {cohort.name}"
            ret_dict["breakdown_value"] = cohort.pk
    return ret_dict


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    properties = kwargs.pop("properties", {})
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": name, "properties": properties}])
    return action


def _create_cohort(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    groups = kwargs.pop("groups")
    cohort = Cohort.objects.create(team=team, name=name, groups=groups, last_calculation=timezone.now())
    cohort.calculate_people_ch(pending_version=0)
    return cohort


def _props(dict: dict):
    props = dict.get("properties", None)
    if not props:
        return None

    if isinstance(props, list):
        raw_properties = {
            "type": "AND",
            "values": [{"type": "AND", "values": props}],
        }
    else:
        raw_properties = {
            "type": "AND",
            "values": [{"type": "AND", "values": [props]}],
        }

    return PropertyGroupFilter(**clean_global_properties(raw_properties))


def convert_filter_to_trends_query(filter: Filter) -> TrendsQuery:
    filter_as_dict = filter.to_dict()

    events: list[EventsNode] = []
    actions: list[ActionsNode] = []

    for event in filter.events:
        if isinstance(event._data.get("properties", None), list):
            properties = clean_entity_properties(event._data.get("properties", None))
        elif event._data.get("properties", None) is not None:
            values = event._data.get("properties", None).get("values", None)
            properties = clean_entity_properties(values)
        else:
            properties = None

        events.append(
            EventsNode(
                event=event.id,
                name=event.name,
                custom_name=event.custom_name,
                math=event.math,
                math_property=event.math_property,
                math_hogql=event.math_hogql,
                math_group_type_index=event.math_group_type_index,
                properties=properties,
            )
        )

    for action in filter.actions:
        if isinstance(action._data.get("properties", None), list):
            properties = clean_entity_properties(action._data.get("properties", None))
        elif action._data.get("properties", None) is not None:
            values = action._data.get("properties", None).get("values", None)
            properties = clean_entity_properties(values)
        else:
            properties = None

        actions.append(
            ActionsNode(
                id=action.id,
                name=action.name,
                custom_name=action.custom_name,
                math=action.math,
                math_property=action.math_property,
                math_hogql=action.math_hogql,
                math_group_type_index=action.math_group_type_index,
                properties=properties,
            )
        )

    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = [*events, *actions]

    tq = TrendsQuery(
        series=series,
        kind="TrendsQuery",
        filterTestAccounts=filter.filter_test_accounts,
        dateRange=DateRange(date_from=filter_as_dict.get("date_from"), date_to=filter_as_dict.get("date_to")),
        samplingFactor=filter.sampling_factor,
        aggregation_group_type_index=filter.aggregation_group_type_index,
        breakdownFilter=BreakdownFilter(
            breakdown=filter.breakdown,
            breakdown_type=filter.breakdown_type,
            breakdown_normalize_url=filter.breakdown_normalize_url,
            breakdowns=filter.breakdowns,
            breakdown_group_type_index=filter.breakdown_group_type_index,
            breakdown_histogram_bin_count=filter.breakdown_histogram_bin_count,
            breakdown_limit=filter._breakdown_limit,
        ),
        properties=_props(filter.to_dict()),
        interval=filter.interval,
        trendsFilter=TrendsFilter(
            display=filter.display,
            breakdown_histogram_bin_count=filter.breakdown_histogram_bin_count,
            formula=filter.formula,
            smoothingIntervals=filter.smoothing_intervals,
        ),
        compareFilter=CompareFilter(compare=filter.compare, compare_to=filter.compare_to),
    )

    return tq


@override_settings(IN_UNIT_TESTING=True)
class TestTrends(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _run(self, filter: Filter, team: Team):
        flush_persons_and_events()

        trend_query = convert_filter_to_trends_query(filter)
        tqr = TrendsQueryRunner(team=team, query=trend_query)
        return tqr.calculate().results

    def _get_actors(self, filters: dict[str, Any], **kwargs) -> list[list[Any]]:
        trends_query = cast(TrendsQuery, filter_to_query(filters))
        return get_actors(trends_query=trends_query, **kwargs)

    def _create_event(self, **kwargs):
        _create_event(**kwargs)
        props = kwargs.get("properties")
        if props is not None:
            for key, value in props.items():
                prop_def_exists = PropertyDefinition.objects.filter(team=self.team, name=key).exists()
                if prop_def_exists is False:
                    if isinstance(value, str):
                        type = "String"
                    elif isinstance(value, bool):
                        type = "Boolean"
                    elif isinstance(value, int):
                        type = "Numeric"
                    else:
                        type = "String"

                    PropertyDefinition.objects.create(
                        team=self.team,
                        name=key,
                        property_type=type,
                        type=PropertyDefinition.Type.EVENT,
                    )

    def _create_person(self, **kwargs):
        person = _create_person(**kwargs)
        props = kwargs.get("properties")
        if props is not None:
            for key, value in props.items():
                prop_def_exists = PropertyDefinition.objects.filter(team=self.team, name=key).exists()
                if prop_def_exists is False:
                    if isinstance(value, str):
                        type = "String"
                    elif isinstance(value, bool):
                        type = "Boolean"
                    elif isinstance(value, int):
                        type = "Numeric"
                    else:
                        type = "String"

                    PropertyDefinition.objects.create(
                        team=self.team,
                        name=key,
                        property_type=type,
                        type=PropertyDefinition.Type.PERSON,
                    )
        return person

    def _create_group(self, **kwargs):
        create_group(**kwargs)
        props = kwargs.get("properties")
        index = kwargs.get("group_type_index")

        if props is not None:
            for key, value in props.items():
                prop_def_exists = PropertyDefinition.objects.filter(team=self.team, name=key).exists()
                if prop_def_exists is False:
                    if isinstance(value, str):
                        type = "String"
                    elif isinstance(value, bool):
                        type = "Boolean"
                    elif isinstance(value, int):
                        type = "Numeric"
                    else:
                        type = "String"

                    PropertyDefinition.objects.create(
                        team=self.team,
                        name=key,
                        property_type=type,
                        group_type_index=index,
                        type=PropertyDefinition.Type.GROUP,
                    )

    def _create_events(self, use_time=False) -> tuple[Action, Person]:
        person = self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        _, _, secondTeam = Organization.objects.bootstrap(None, team_fields={"api_token": "token456"})

        freeze_without_time = ["2019-12-24", "2020-01-01", "2020-01-02"]
        freeze_with_time = [
            "2019-12-24 03:45:34",
            "2020-01-01 00:06:34",
            "2020-01-02 16:34:34",
        ]

        freeze_args = freeze_without_time
        if use_time:
            freeze_args = freeze_with_time

        with freeze_time(freeze_args[0]):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$bool_prop": True},
            )

        with freeze_time(freeze_args[1]):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$bool_prop": False},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="anonymous_id",
                properties={"$bool_prop": False},
            )
            self._create_event(team=self.team, event="sign up", distinct_id="blabla")
        with freeze_time(freeze_args[2]):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={
                    "$some_property": "other_value",
                    "$some_numerical_prop": 80,
                },
            )
            self._create_event(team=self.team, event="no events", distinct_id="blabla")

            # second team should have no effect
            self._create_event(
                team=secondTeam,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "other_value"},
            )

        _create_action(team=self.team, name="no events")
        sign_up_action = _create_action(team=self.team, name="sign up")

        flush_persons_and_events()

        return sign_up_action, person

    def _create_breakdown_events(self):
        freeze_without_time = ["2020-01-02"]

        with freeze_time(freeze_without_time[0]):
            for i in range(25):
                self._create_event(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": i},
                )
        _create_action(team=self.team, name="sign up")

    def _create_breakdown_url_events(self):
        freeze_without_time = ["2020-01-02"]

        with freeze_time(freeze_without_time[0]):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$current_url": "http://hogflix/first"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$current_url": "http://hogflix/first/"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$current_url": "http://hogflix/second"},
            )

    def _create_event_count_per_actor_events(self):
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"fruit": "mango"},
        )
        self._create_person(team_id=self.team.pk, distinct_ids=["tintin"], properties={"fruit": "mango"})
        self._create_person(team_id=self.team.pk, distinct_ids=["murmur"], properties={})  # No fruit here
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["reeree"],
            properties={"fruit": "tomato"},
        )

        with freeze_time("2020-01-01 00:06:02"):
            self._create_event(
                team=self.team,
                event="viewed video",
                distinct_id="anonymous_id",
                properties={"color": "red", "$group_0": "bouba"},
            )
            self._create_event(
                team=self.team,
                event="viewed video",
                distinct_id="blabla",
                properties={"$group_0": "bouba"},
            )  # No color here
            self._create_event(
                team=self.team,
                event="viewed video",
                distinct_id="reeree",
                properties={"color": "blue", "$group_0": "bouba"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="tintin",
                properties={"$group_0": "kiki"},
            )

        with freeze_time("2020-01-03 19:06:34"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="murmur",
                properties={"$group_0": "kiki"},
            )

        with freeze_time("2020-01-04 23:17:00"):
            self._create_event(
                team=self.team,
                event="viewed video",
                distinct_id="tintin",
                properties={"color": "red", "$group_0": "kiki"},
            )

        with freeze_time("2020-01-05 19:06:34"):
            self._create_event(
                team=self.team,
                event="viewed video",
                distinct_id="blabla",
                properties={"color": "blue", "$group_0": "bouba"},
            )
            self._create_event(
                team=self.team,
                event="viewed video",
                distinct_id="tintin",
                properties={"color": "red"},
            )  # No group here
            self._create_event(
                team=self.team,
                event="viewed video",
                distinct_id="tintin",
                properties={"color": "red", "$group_0": "bouba"},
            )
            self._create_event(
                team=self.team,
                event="viewed video",
                distinct_id="tintin",
                properties={"color": "blue", "$group_0": "kiki"},
            )

    def test_trends_per_day(self):
        self._create_events()
        with freeze_time("2020-01-04T13:00:01Z"):
            # with self.assertNumQueries(16):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-7d",
                        "events": [{"id": "sign up"}, {"id": "no events"}],
                    },
                ),
                self.team,
            )
        self.assertEqual(response[0]["label"], "sign up")
        self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
        self.assertEqual(response[0]["data"][4], 3.0)
        self.assertEqual(response[0]["labels"][5], "2-Jan-2020")
        self.assertEqual(response[0]["data"][5], 1.0)

    # just make sure this doesn't error
    def test_no_props_string(self):
        PropertyDefinition.objects.create(
            team=self.team,
            name="$some_property",
            property_type="String",
            type=PropertyDefinition.Type.EVENT,
        )

        with freeze_time("2020-01-04T13:01:01Z"):
            self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdown": "$some_property",
                        "events": [
                            {
                                "id": "sign up",
                                "name": "sign up",
                                "type": "events",
                                "order": 0,
                            },
                            {"id": "no events"},
                        ],
                    },
                ),
                self.team,
            )
            self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdowns": [{"property": "$some_property"}],
                        "events": [
                            {
                                "id": "sign up",
                                "name": "sign up",
                                "type": "events",
                                "order": 0,
                            },
                            {"id": "no events"},
                        ],
                    },
                ),
                self.team,
            )

    def test_no_props_numeric(self):
        PropertyDefinition.objects.create(
            team=self.team,
            name="$some_property",
            property_type="Numeric",
            type=PropertyDefinition.Type.EVENT,
        )

        with freeze_time("2020-01-04T13:01:01Z"):
            self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdown": "$some_property",
                        "events": [
                            {
                                "id": "sign up",
                                "name": "sign up",
                                "type": "events",
                                "order": 0,
                            },
                            {"id": "no events"},
                        ],
                    },
                ),
                self.team,
            )
            self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdowns": [{"property": "$some_property"}],
                        "events": [
                            {
                                "id": "sign up",
                                "name": "sign up",
                                "type": "events",
                                "order": 0,
                            },
                            {"id": "no events"},
                        ],
                    },
                ),
                self.team,
            )

    def test_no_props_boolean(self):
        PropertyDefinition.objects.create(
            team=self.team,
            name="$some_property",
            property_type="Boolean",
            type=PropertyDefinition.Type.EVENT,
        )

        with freeze_time("2020-01-04T13:01:01Z"):
            self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdown": "$some_property",
                        "events": [
                            {
                                "id": "sign up",
                                "name": "sign up",
                                "type": "events",
                                "order": 0,
                            },
                            {"id": "no events"},
                        ],
                    },
                ),
                self.team,
            )
            self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdowns": [{"property": "$some_property"}],
                        "events": [
                            {
                                "id": "sign up",
                                "name": "sign up",
                                "type": "events",
                                "order": 0,
                            },
                            {"id": "no events"},
                        ],
                    },
                ),
                self.team,
            )

    def test_trends_per_day_48hours(self):
        self._create_events()
        with freeze_time("2020-01-03T13:00:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-48h",
                        "interval": "day",
                        "events": [{"id": "sign up"}, {"id": "no events"}],
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["data"][1], 1.0)
        self.assertEqual(response[0]["labels"][1], "2-Jan-2020")

    @snapshot_clickhouse_queries
    def test_trends_per_day_cumulative(self):
        self._create_events()
        with freeze_time("2020-01-04T13:00:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-7d",
                        "display": "ActionsLineGraphCumulative",
                        "events": [{"id": "sign up"}],
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["label"], "sign up")
        self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
        self.assertEqual(response[0]["data"][4], 3.0)
        self.assertEqual(response[0]["labels"][5], "2-Jan-2020")
        self.assertEqual(response[0]["data"][5], 4.0)

    @snapshot_clickhouse_queries
    def test_trends_per_day_dau_cumulative(self):
        self._create_events()
        with freeze_time("2020-01-03T13:00:01Z"):
            self._create_person(
                team_id=self.team.pk,
                distinct_ids=["new_user"],
                properties={"$some_prop": "some_val"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="new_user",
                properties={"$some_property": "value", "$bool_prop": False},
            )
            flush_persons_and_events()
        with freeze_time("2020-01-04T13:00:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-7d",
                        "display": "ActionsLineGraphCumulative",
                        "events": [{"id": "sign up", "math": "dau"}],
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["label"], "sign up")
        self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
        self.assertEqual(response[0]["data"][4], 1.0)
        self.assertEqual(response[0]["labels"][5], "2-Jan-2020")
        self.assertEqual(response[0]["data"][5], 1.0)
        self.assertEqual(response[0]["labels"][6], "3-Jan-2020")
        self.assertEqual(response[0]["data"][6], 2.0)

    @snapshot_clickhouse_queries
    def test_trends_groups_per_day(self):
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )
        self._create_event_count_per_actor_events()
        with freeze_time("2020-01-06T13:00:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-7d",
                        "display": "ActionsLineGraph",
                        "events": [
                            {
                                "id": "viewed video",
                                "math": "unique_group",
                                "math_group_type_index": 0,
                            }
                        ],
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["label"], "viewed video")
        self.assertEqual(response[0]["labels"][-1], "6-Jan-2020")
        self.assertEqual(response[0]["data"], [0.0, 0.0, 1.0, 0, 0, 1, 2, 0])

    @snapshot_clickhouse_queries
    def test_trends_groups_per_day_cumulative(self):
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )
        self._create_event_count_per_actor_events()
        with freeze_time("2020-01-06T13:00:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-7d",
                        "display": "ActionsLineGraphCumulative",
                        "events": [
                            {
                                "id": "viewed video",
                                "math": "unique_group",
                                "math_group_type_index": 0,
                            }
                        ],
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["label"], "viewed video")
        self.assertEqual(response[0]["labels"][-1], "6-Jan-2020")
        self.assertEqual(response[0]["data"], [0.0, 0.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.0])

    @also_test_with_person_on_events_v2
    @snapshot_clickhouse_queries
    def test_trends_breakdown_cumulative(self):
        self._create_events()
        with freeze_time("2020-01-04T13:00:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-7d",
                        "display": "ActionsLineGraphCumulative",
                        "events": [{"id": "sign up", "math": "dau"}],
                        "breakdown": "$some_property",
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["label"], "value")
        self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
        self.assertEqual(response[0]["data"], [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])

        self.assertEqual(response[1]["label"], "other_value")
        self.assertEqual(response[1]["labels"][4], "1-Jan-2020")
        self.assertEqual(response[1]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0])

        self.assertEqual(response[2]["label"], "$$_posthog_breakdown_null_$$")
        self.assertEqual(response[2]["labels"][4], "1-Jan-2020")
        self.assertEqual(response[2]["data"], [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])

    @snapshot_clickhouse_queries
    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_trends_breakdown_normalize_url(self):
        self._create_breakdown_url_events()
        with freeze_time("2020-01-04T13:00:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-7d",
                        "display": "ActionsLineGraphCumulative",
                        "events": [{"id": "sign up", "math": "dau"}],
                        "breakdown": "$current_url",
                        "breakdown_normalize_url": True,
                    },
                ),
                self.team,
            )

        labels = [item["label"] for item in response]
        assert sorted(labels) == ["http://hogflix/first", "http://hogflix/second"]
        breakdown_values = [item["breakdown_value"] for item in response]
        assert sorted(breakdown_values) == sorted(labels)

    def test_trends_single_aggregate_dau(self):
        self._create_events()
        with freeze_time("2020-01-04T13:00:01Z"):
            daily_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "interval": "week",
                        "events": [{"id": "sign up", "math": "dau"}],
                    },
                ),
                self.team,
            )

        with freeze_time("2020-01-04T13:00:01Z"):
            weekly_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "interval": "day",
                        "events": [{"id": "sign up", "math": "dau"}],
                    },
                ),
                self.team,
            )

        self.assertEqual(daily_response[0]["aggregated_value"], 1)
        self.assertEqual(
            daily_response[0]["aggregated_value"],
            weekly_response[0]["aggregated_value"],
        )

    @also_test_with_materialized_columns(["$math_prop"])
    def test_trends_single_aggregate_math(self):
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        with freeze_time("2020-01-01 00:06:34"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$math_prop": 1},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$math_prop": 1},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$math_prop": 1},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$math_prop": 2},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$math_prop": 3},
            )

        with freeze_time("2020-01-02 00:06:34"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$math_prop": 4},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$math_prop": 4},
            )

        with freeze_time("2020-01-04T13:00:01Z"):
            daily_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "interval": "week",
                        "events": [
                            {
                                "id": "sign up",
                                "math": "median",
                                "math_property": "$math_prop",
                            }
                        ],
                    },
                ),
                self.team,
            )

        with freeze_time("2020-01-04T13:00:01Z"):
            weekly_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "interval": "day",
                        "events": [
                            {
                                "id": "sign up",
                                "math": "median",
                                "math_property": "$math_prop",
                            }
                        ],
                    },
                ),
                self.team,
            )

        self.assertEqual(daily_response[0]["aggregated_value"], 2.0)
        self.assertEqual(
            daily_response[0]["aggregated_value"],
            weekly_response[0]["aggregated_value"],
        )

    @snapshot_clickhouse_queries
    def test_trends_with_session_property_single_aggregate_math(self):
        s1 = str(uuid7("2020-01-01", 1))
        s2 = str(uuid7("2020-01-01", 2))
        s3 = str(uuid7("2020-01-01", 3))
        s4 = str(uuid7("2020-01-01", 4))
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla2"],
            properties={"$some_prop": "some_val"},
        )

        self._create_event(
            team=self.team,
            event="sign up before",
            distinct_id="blabla",
            properties={"$session_id": s1},
            timestamp="2020-01-01 00:06:30",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s1},
            timestamp="2020-01-01 00:06:34",
        )
        self._create_event(
            team=self.team,
            event="sign up later",
            distinct_id="blabla",
            properties={"$session_id": s1},
            timestamp="2020-01-01 00:06:35",
        )
        # First session lasted 5 seconds
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla2",
            properties={"$session_id": s2},
            timestamp="2020-01-01 00:06:35",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla2",
            properties={"$session_id": s2},
            timestamp="2020-01-01 00:06:45",
        )
        # Second session lasted 10 seconds

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s3},
            timestamp="2020-01-01 00:06:45",
        )
        # Third session lasted 0 seconds

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s4},
            timestamp="2020-01-02 00:06:30",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s4},
            timestamp="2020-01-02 00:06:45",
        )
        # Fourth session lasted 15 seconds

        with freeze_time("2020-01-04T13:00:01Z"):
            daily_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "interval": "week",
                        "events": [
                            {
                                "id": "sign up",
                                "math": "median",
                                "math_property": "$session_duration",
                            }
                        ],
                    },
                ),
                self.team,
            )

        with freeze_time("2020-01-04T13:00:01Z"):
            weekly_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "interval": "day",
                        "events": [
                            {
                                "id": "sign up",
                                "math": "median",
                                "math_property": "$session_duration",
                            }
                        ],
                    },
                ),
                self.team,
            )

        self.assertEqual(daily_response[0]["aggregated_value"], 7.5)
        self.assertEqual(
            daily_response[0]["aggregated_value"],
            weekly_response[0]["aggregated_value"],
        )

    def test_unique_session_with_session_breakdown(self):
        s1 = str(uuid7("2020-01-01", 1))
        s2 = str(uuid7("2020-01-01", 2))
        s3 = str(uuid7("2020-01-01", 3))
        s4 = str(uuid7("2020-01-01", 4))
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla2"],
            properties={"$some_prop": "some_val"},
        )

        self._create_event(
            team=self.team,
            event="sign up before",
            distinct_id="blabla",
            properties={"$session_id": s1},
            timestamp="2020-01-01 00:06:30",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s1},
            timestamp="2020-01-01 00:06:34",
        )
        self._create_event(
            team=self.team,
            event="sign up later",
            distinct_id="blabla",
            properties={"$session_id": s1},
            timestamp="2020-01-01 00:06:35",
        )
        # First session lasted 5 seconds
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla2",
            properties={"$session_id": s2},
            timestamp="2020-01-01 00:06:35",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla2",
            properties={"$session_id": s2},
            timestamp="2020-01-01 00:06:45",
        )
        # Second session lasted 10 seconds

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s3},
            timestamp="2020-01-01 00:06:45",
        )
        # Third session lasted 0 seconds

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s4},
            timestamp="2020-01-02 00:06:30",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s4},
            timestamp="2020-01-02 00:06:45",
        )
        # Fourth session lasted 15 seconds

        with freeze_time("2020-01-04T13:00:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": "ActionsLineGraph",
                        "interval": "day",
                        "events": [{"id": "sign up", "math": "unique_session"}],
                        "breakdown": "$session_duration",
                        "breakdown_type": "session",
                        "insight": "TRENDS",
                        "breakdown_histogram_bin_count": 3,
                        "properties": [{"key": "$some_prop", "value": "some_val", "type": "person"}],
                        "date_from": "-3d",
                    },
                ),
                self.team,
            )

            self.assertEqual(
                [(item["breakdown_value"], item["count"], item["data"]) for item in response],
                [("[10,15.01]", 2.0, [1, 1, 0, 0]), ("[0,5]", 1.0, [1, 0, 0, 0]), ("[5,10]", 1.0, [1, 0, 0, 0])],
            )

    @also_test_with_person_on_events_v2
    @also_test_with_materialized_columns(person_properties=["name"], verify_no_jsonextract=False)
    def test_trends_breakdown_single_aggregate_cohorts(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["Jane"], properties={"name": "Jane"})
        self._create_person(team_id=self.team.pk, distinct_ids=["John"], properties={"name": "John"})
        self._create_person(team_id=self.team.pk, distinct_ids=["Jill"], properties={"name": "Jill"})
        cohort1 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "Jane", "type": "person"}]}],
        )
        cohort2 = _create_cohort(
            team=self.team,
            name="cohort2",
            groups=[{"properties": [{"key": "name", "value": "John", "type": "person"}]}],
        )
        cohort3 = _create_cohort(
            team=self.team,
            name="cohort3",
            groups=[{"properties": [{"key": "name", "value": "Jill", "type": "person"}]}],
        )
        with freeze_time("2020-01-01 00:06:34"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="John",
                properties={"$some_property": "value", "$browser": "Chrome"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="John",
                properties={"$some_property": "value", "$browser": "Chrome"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="Jill",
                properties={"$some_property": "value", "$browser": "Safari"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="Jill",
                properties={"$some_property": "value", "$browser": "Safari"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="Jill",
                properties={"$some_property": "value", "$browser": "Safari"},
            )

        with freeze_time("2020-01-02 00:06:34"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="Jane",
                properties={"$some_property": "value", "$browser": "Safari"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="Jane",
                properties={"$some_property": "value", "$browser": "Safari"},
            )
        with freeze_time("2020-01-04T13:00:01Z"):
            event_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "breakdown": json.dumps([cohort1.pk, cohort2.pk, cohort3.pk, "all"]),
                        "breakdown_type": "cohort",
                        "events": [{"id": "sign up"}],
                    },
                ),
                self.team,
            )

        for result in event_response:
            if result["label"] == "sign up - cohort1":
                self.assertEqual(result["aggregated_value"], 2)
            elif result["label"] == "sign up - cohort2":
                self.assertEqual(result["aggregated_value"], 2)
            elif result["label"] == "sign up - cohort3":
                self.assertEqual(result["aggregated_value"], 3)
            else:
                self.assertEqual(result["aggregated_value"], 7)

    def test_trends_breakdown_single_aggregate(self):
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        with freeze_time("2020-01-01 00:06:34"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Chrome"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Chrome"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari"},
            )

        with freeze_time("2020-01-02 00:06:34"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari"},
            )

        with freeze_time("2020-01-04T13:00:01Z"):
            daily_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "breakdown": "$browser",
                        "events": [{"id": "sign up"}],
                    },
                ),
                self.team,
            )

        for result in daily_response:
            if result["breakdown_value"] == "Chrome":
                self.assertEqual(result["aggregated_value"], 2)
            else:
                self.assertEqual(result["aggregated_value"], 5)

    def test_trends_multiple_breakdowns_single_aggregate(self):
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        with freeze_time("2020-01-01 00:06:34"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Chrome", "$variant": "1"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Chrome", "$variant": "2"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari", "$variant": "1"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari", "$variant": "1"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari", "$variant": "2"},
            )

        with freeze_time("2020-01-02 00:06:34"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari", "$variant": "2"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari", "$variant": "2"},
            )

        with freeze_time("2020-01-04T13:00:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "breakdowns": [
                            {"property": "$browser"},
                            {"property": "$variant"},
                        ],
                        "events": [{"id": "sign up"}],
                    },
                ),
                self.team,
            )

        for result in response:
            self.assertIsInstance(result["breakdown_value"], list)

        self.assertEqual(response[0]["breakdown_value"], ["Safari", "2"])
        self.assertEqual(response[1]["breakdown_value"], ["Safari", "1"])
        self.assertEqual(response[2]["breakdown_value"], ["Chrome", "1"])
        self.assertEqual(response[3]["breakdown_value"], ["Chrome", "2"])
        self.assertEqual(response[0]["aggregated_value"], 3)
        self.assertEqual(response[1]["aggregated_value"], 2)
        self.assertEqual(response[2]["aggregated_value"], 1)
        self.assertEqual(response[3]["aggregated_value"], 1)

    def test_trends_breakdown_single_aggregate_with_zero_person_ids(self):
        # only a person-on-event test
        if not get_instance_setting("PERSON_ON_EVENTS_ENABLED"):
            return True

        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        with freeze_time("2020-01-01 00:06:34"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Chrome"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Chrome"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla2",
                properties={"$some_property": "value", "$browser": "Chrome"},
                person_id="00000000-0000-0000-0000-000000000000",
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla2",
                properties={"$some_property": "value", "$browser": "Safari"},
                person_id="00000000-0000-0000-0000-000000000000",
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla3",
                properties={"$some_property": "value", "$browser": "xyz"},
                person_id="00000000-0000-0000-0000-000000000000",
            )

        with freeze_time("2020-01-02 00:06:34"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla4",
                properties={"$some_property": "value", "$browser": "Chrome"},
                person_id="00000000-0000-0000-0000-000000000000",
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla2",
                properties={"$some_property": "value", "$browser": "urgh"},
                person_id="00000000-0000-0000-0000-000000000000",
            )

        with freeze_time("2020-01-04T13:00:01Z"):
            daily_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "breakdown": "$browser",
                        "events": [{"id": "sign up"}],
                    },
                ),
                self.team,
            )

        for result in daily_response:
            if result["breakdown_value"] == "Chrome":
                self.assertEqual(result["aggregated_value"], 2)
            else:
                self.assertEqual(result["aggregated_value"], 5)

        # multiple
        with freeze_time("2020-01-04T13:00:01Z"):
            daily_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "breakdowns": [{"property": "$browser"}],
                        "events": [{"id": "sign up"}],
                    },
                ),
                self.team,
            )

        for result in daily_response:
            if result["breakdown_value"] == "Chrome":
                self.assertEqual(result["aggregated_value"], 2)
            else:
                self.assertEqual(result["aggregated_value"], 5)

    def test_trends_breakdown_single_aggregate_math(self):
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        with freeze_time("2020-01-01 00:06:34"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$math_prop": 1},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$math_prop": 1},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$math_prop": 1},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$math_prop": 2},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$math_prop": 3},
            )

        with freeze_time("2020-01-02 00:06:34"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$math_prop": 4},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$math_prop": 4},
            )

        filters: list[dict[str, Any]] = [
            {"breakdown": "$some_property"},
            {"breakdowns": [{"property": "$some_property"}]},
        ]
        for breakdown_filter in filters:
            with freeze_time("2020-01-04T13:00:01Z"):
                daily_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "display": TRENDS_TABLE,
                            "interval": "day",
                            "events": [
                                {
                                    "id": "sign up",
                                    "math": "median",
                                    "math_property": "$math_prop",
                                }
                            ],
                        },
                    ),
                    self.team,
                )

            with freeze_time("2020-01-04T13:00:01Z"):
                weekly_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "display": TRENDS_TABLE,
                            "interval": "week",
                            "events": [
                                {
                                    "id": "sign up",
                                    "math": "median",
                                    "math_property": "$math_prop",
                                }
                            ],
                        },
                    ),
                    self.team,
                )

            self.assertEqual(daily_response[0]["aggregated_value"], 2.0)
            self.assertEqual(
                daily_response[0]["aggregated_value"],
                weekly_response[0]["aggregated_value"],
            )

    @snapshot_clickhouse_queries
    def test_trends_breakdown_with_session_property_single_aggregate_math_and_breakdown(self):
        s1 = str(uuid7("2020-01-01", 1))
        s2 = str(uuid7("2020-01-01", 2))
        s3 = str(uuid7("2020-01-01", 3))
        s4 = str(uuid7("2020-01-01", 4))
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla2"],
            properties={"$some_prop": "some_val"},
        )

        self._create_event(
            team=self.team,
            event="sign up before",
            distinct_id="blabla",
            properties={"$session_id": s1, "$some_property": "value1"},
            timestamp="2020-01-01 00:06:30",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s1, "$some_property": "value1"},
            timestamp="2020-01-01 00:06:34",
        )
        self._create_event(
            team=self.team,
            event="sign up later",
            distinct_id="blabla",
            properties={"$session_id": s1, "$some_property": "value doesnt matter"},
            timestamp="2020-01-01 00:06:35",
        )
        # First session lasted 5 seconds
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla2",
            properties={"$session_id": s2, "$some_property": "value2"},
            timestamp="2020-01-01 00:06:35",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla2",
            properties={"$session_id": s2, "$some_property": "value1"},
            timestamp="2020-01-01 00:06:45",
        )
        # Second session lasted 10 seconds

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s3},
            timestamp="2020-01-01 00:06:45",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s3},
            timestamp="2020-01-01 00:06:46",
        )
        # Third session lasted 1 seconds

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s4, "$some_property": "value2"},
            timestamp="2020-01-02 00:06:30",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s4, "$some_property": "value2"},
            timestamp="2020-01-02 00:06:35",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s4, "$some_property": "value1"},
            timestamp="2020-01-02 00:06:45",
        )
        # Fourth session lasted 15 seconds

        # single breakdown
        with freeze_time("2020-01-04T13:00:33Z"):
            daily_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "interval": "week",
                        "breakdown": "$some_property",
                        "events": [
                            {
                                "id": "sign up",
                                "math": "median",
                                "math_property": "$session_duration",
                            }
                        ],
                    },
                ),
                self.team,
            )

        # value1 has: 5 seconds, 10 seconds, 15 seconds
        # value2 has: 10 seconds, 15 seconds (aggregated by session, so 15 is not double counted)
        # empty has: 1 seconds
        self.assertEqual(
            [resp["breakdown_value"] for resp in daily_response],
            ["value2", "value1", "$$_posthog_breakdown_null_$$"],
        )
        self.assertEqual([resp["aggregated_value"] for resp in daily_response], [12.5, 10, 1])

        with freeze_time("2020-01-04T13:00:01Z"):
            weekly_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "interval": "day",
                        "breakdown": "$some_property",
                        "events": [
                            {
                                "id": "sign up",
                                "math": "median",
                                "math_property": "$session_duration",
                            }
                        ],
                    },
                ),
                self.team,
            )

        self.assertEqual(
            [resp["breakdown_value"] for resp in daily_response],
            [resp["breakdown_value"] for resp in weekly_response],
        )
        self.assertEqual(
            [resp["aggregated_value"] for resp in daily_response],
            [resp["aggregated_value"] for resp in weekly_response],
        )

        # multiple breakdowns
        with freeze_time("2020-01-04T13:00:33Z"):
            daily_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "interval": "week",
                        "breakdowns": [{"property": "$some_property"}],
                        "events": [
                            {
                                "id": "sign up",
                                "math": "median",
                                "math_property": "$session_duration",
                            }
                        ],
                    },
                ),
                self.team,
            )

        # value1 has: 5 seconds, 10 seconds, 15 seconds
        # value2 has: 10 seconds, 15 seconds (aggregated by session, so 15 is not double counted)
        # empty has: 1 seconds
        self.assertEqual(
            [resp["breakdown_value"] for resp in daily_response],
            [["value2"], ["value1"], ["$$_posthog_breakdown_null_$$"]],
        )
        self.assertEqual([resp["aggregated_value"] for resp in daily_response], [12.5, 10, 1])

        with freeze_time("2020-01-04T13:00:01Z"):
            weekly_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "interval": "day",
                        "breakdowns": [{"property": "$some_property"}],
                        "events": [
                            {
                                "id": "sign up",
                                "math": "median",
                                "math_property": "$session_duration",
                            }
                        ],
                    },
                ),
                self.team,
            )

        self.assertEqual(
            [resp["breakdown_value"] for resp in daily_response],
            [resp["breakdown_value"] for resp in weekly_response],
        )
        self.assertEqual(
            [resp["aggregated_value"] for resp in daily_response],
            [resp["aggregated_value"] for resp in weekly_response],
        )

    @snapshot_clickhouse_queries
    def test_trends_person_breakdown_with_session_property_single_aggregate_math_and_breakdown(self):
        s1 = str(uuid7("2020-01-01", 1))
        s2 = str(uuid7("2020-01-01", 2))
        s3 = str(uuid7("2020-01-01", 3))
        s4 = str(uuid7("2020-01-01", 4))
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla2"],
            properties={"$some_prop": "another_val"},
        )

        self._create_event(
            team=self.team,
            event="sign up before",
            distinct_id="blabla",
            properties={"$session_id": s1, "$some_property": "value1"},
            timestamp="2020-01-01 00:06:30",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s1, "$some_property": "value1"},
            timestamp="2020-01-01 00:06:34",
        )
        self._create_event(
            team=self.team,
            event="sign up later",
            distinct_id="blasbla",
            properties={"$session_id": s1, "$some_property": "value doesnt matter"},
            timestamp="2020-01-01 00:06:35",
        )
        # First session lasted 5 seconds
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla2",
            properties={"$session_id": s2, "$some_property": "value2"},
            timestamp="2020-01-01 00:06:35",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla2",
            properties={"$session_id": s2, "$some_property": "value1"},
            timestamp="2020-01-01 00:06:45",
        )
        # Second session lasted 10 seconds

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s3},
            timestamp="2020-01-01 00:06:45",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s3},
            timestamp="2020-01-01 00:06:46",
        )
        # Third session lasted 1 seconds

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s4, "$some_property": "value2"},
            timestamp="2020-01-02 00:06:30",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s4, "$some_property": "value2"},
            timestamp="2020-01-02 00:06:35",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s4, "$some_property": "value1"},
            timestamp="2020-01-02 00:06:45",
        )
        # Fourth session lasted 15 seconds

        with freeze_time("2020-01-04T13:00:01Z"):
            daily_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "interval": "week",
                        "breakdown": "$some_prop",
                        "breakdown_type": "person",
                        "events": [
                            {
                                "id": "sign up",
                                "math": "median",
                                "math_property": "$session_duration",
                            }
                        ],
                    },
                ),
                self.team,
            )

        # another_val has: 10 seconds
        # some_val has: 1, 5 seconds, 15 seconds
        self.assertEqual(
            sorted([resp["breakdown_value"] for resp in daily_response]),
            ["another_val", "some_val"],
        )
        self.assertEqual(sorted([resp["aggregated_value"] for resp in daily_response]), [5.0, 10.0])

        with freeze_time("2020-01-04T13:00:01Z"):
            daily_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "interval": "week",
                        "breakdowns": [{"type": "person", "property": "$some_prop"}],
                        "events": [
                            {
                                "id": "sign up",
                                "math": "median",
                                "math_property": "$session_duration",
                            }
                        ],
                    },
                ),
                self.team,
            )

        # another_val has: 10 seconds
        # some_val has: 1, 5 seconds, 15 seconds
        self.assertEqual(
            sorted([resp["breakdown_value"] for resp in daily_response]),
            [["another_val"], ["some_val"]],
        )
        self.assertEqual(sorted([resp["aggregated_value"] for resp in daily_response]), [5.0, 10.0])

    @snapshot_clickhouse_queries
    def test_trends_any_event_total_count(self):
        self._create_events()
        with freeze_time("2020-01-04T13:00:01Z"):
            response1 = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_LINEAR,
                        "interval": "day",
                        "events": [{"id": None, "math": "total"}],
                    },
                ),
                self.team,
            )
            response2 = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_LINEAR,
                        "interval": "day",
                        "events": [{"id": "sign up", "math": "total"}],
                    },
                ),
                self.team,
            )
        self.assertEqual(response1[0]["count"], 5)
        self.assertEqual(response2[0]["count"], 4)

    @also_test_with_materialized_columns(["$math_prop", "$some_property"])
    def test_trends_breakdown_with_math_func(self):
        with freeze_time("2020-01-01 00:06:34"):
            for i in range(20):
                self._create_person(team_id=self.team.pk, distinct_ids=[f"person{i}"])
                self._create_event(
                    team=self.team,
                    event="sign up",
                    distinct_id=f"person{i}",
                    properties={"$some_property": f"value_{i}", "$math_prop": 1},
                )
                self._create_event(
                    team=self.team,
                    event="sign up",
                    distinct_id=f"person{i}",
                    properties={"$some_property": f"value_{i}", "$math_prop": 1},
                )

            self._create_person(team_id=self.team.pk, distinct_ids=[f"person21"])
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id=f"person21",
                properties={"$some_property": "value_21", "$math_prop": 25},
            )

        # single breakdown
        with freeze_time("2020-01-04T13:00:01Z"):
            daily_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "interval": "day",
                        "breakdown": "$some_property",
                        "events": [
                            {
                                "id": "sign up",
                                "math": "p90",
                                "math_property": "$math_prop",
                            }
                        ],
                    },
                ),
                self.team,
            )

        breakdown_vals = [val["breakdown_value"] for val in daily_response]
        self.assertTrue("value_21" in breakdown_vals)

        # multiple breakdown
        with freeze_time("2020-01-04T13:00:01Z"):
            daily_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "display": TRENDS_TABLE,
                        "interval": "day",
                        "breakdowns": [{"property": "$some_property"}],
                        "events": [
                            {
                                "id": "sign up",
                                "math": "p90",
                                "math_property": "$math_prop",
                            }
                        ],
                    },
                ),
                self.team,
            )

        breakdown_vals = [val["breakdown_value"] for val in daily_response]
        self.assertTrue(["value_21"] in breakdown_vals)

    @snapshot_clickhouse_queries
    def test_trends_compare_day_interval_relative_range(self):
        self._create_events()
        with freeze_time("2020-01-04T13:00:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "compare": "true",
                        "date_from": "-7d",
                        "events": [{"id": "sign up"}],
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["label"], "sign up")
        self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
        self.assertEqual(response[0]["data"][4], 3.0)
        self.assertEqual(response[0]["labels"][5], "2-Jan-2020")
        self.assertEqual(response[0]["data"][5], 1.0)
        self.assertEqual(
            response[0]["days"],
            [
                "2019-12-28",  # -7d, current period
                "2019-12-29",  # -6d, current period
                "2019-12-30",  # -5d, current period
                "2019-12-31",  # -4d, current period
                "2020-01-01",  # -3d, current period
                "2020-01-02",  # -2d, current period
                "2020-01-03",  # -1d, current period
                "2020-01-04",  # -0d, current period (this one's ongoing!)
            ],
        )

        self.assertEqual(
            response[1]["days"],
            [
                "2019-12-21",  # -7d, previous period
                "2019-12-22",  # -6d, previous period
                "2019-12-23",  # -5d, previous period
                "2019-12-24",  # -4d, previous period
                "2019-12-25",  # -3d, previous period
                "2019-12-26",  # -2d, previous period
                "2019-12-27",  # -1d, previous period
                "2019-12-28",  # duplicated to make weekdays align between current and previous
            ],
        )
        self.assertEqual(response[1]["label"], "sign up")
        self.assertEqual(response[1]["labels"][3], "24-Dec-2019")
        self.assertEqual(response[1]["data"][3], 1.0)
        self.assertEqual(response[1]["labels"][4], "25-Dec-2019")
        self.assertEqual(response[1]["data"][4], 0.0)

        with freeze_time("2020-01-04T13:00:01Z"):
            no_compare_response = self._run(
                Filter(
                    team=self.team,
                    data={"compare": "false", "events": [{"id": "sign up"}]},
                ),
                self.team,
            )

        self.assertEqual(no_compare_response[0]["label"], "sign up")
        self.assertEqual(no_compare_response[0]["labels"][4], "1-Jan-2020")
        self.assertEqual(no_compare_response[0]["data"][4], 3.0)
        self.assertEqual(no_compare_response[0]["labels"][5], "2-Jan-2020")
        self.assertEqual(no_compare_response[0]["data"][5], 1.0)

    def test_trends_compare_day_interval_fixed_range_single(self):
        self._create_events(use_time=True)
        with freeze_time("2020-01-02T20:17:00Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "compare": "true",
                        # A fixed single-day range requires different handling than a relative range like -7d
                        "date_from": "2020-01-02",
                        "interval": "day",
                        "events": [{"id": "sign up"}],
                    },
                ),
                self.team,
            )

        self.assertEqual(
            response[0]["days"],
            [
                "2020-01-02",  # Current day
            ],
        )
        self.assertEqual(
            response[0]["data"],
            [1],
        )
        self.assertEqual(
            response[1]["days"],
            [
                "2020-01-01",  # Previous day
            ],
        )
        self.assertEqual(
            response[1]["data"],
            [
                3,
            ],
        )

    def test_trends_compare_hour_interval_relative_range(self):
        self._create_events(use_time=True)
        with freeze_time("2020-01-02T20:17:00Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "compare": "true",
                        "date_from": "dStart",
                        "interval": "hour",
                        "events": [{"id": "sign up"}],
                    },
                ),
                self.team,
            )

        self.assertEqual(
            response[0]["days"],
            [
                "2020-01-02 00:00:00",
                "2020-01-02 01:00:00",
                "2020-01-02 02:00:00",
                "2020-01-02 03:00:00",
                "2020-01-02 04:00:00",
                "2020-01-02 05:00:00",
                "2020-01-02 06:00:00",
                "2020-01-02 07:00:00",
                "2020-01-02 08:00:00",
                "2020-01-02 09:00:00",
                "2020-01-02 10:00:00",
                "2020-01-02 11:00:00",
                "2020-01-02 12:00:00",
                "2020-01-02 13:00:00",
                "2020-01-02 14:00:00",
                "2020-01-02 15:00:00",
                "2020-01-02 16:00:00",
                "2020-01-02 17:00:00",
                "2020-01-02 18:00:00",
                "2020-01-02 19:00:00",
                "2020-01-02 20:00:00",
            ],
        )
        self.assertEqual(
            response[0]["data"],
            [
                0,  # 00:00
                0,  # 01:00
                0,  # 02:00
                0,  # 03:00
                0,  # 04:00
                0,  # 05:00
                0,  # 06:00
                0,  # 07:00
                0,  # 08:00
                0,  # 09:00
                0,  # 10:00
                0,  # 11:00
                0,  # 12:00
                0,  # 13:00
                0,  # 14:00
                0,  # 15:00
                1,  # 16:00
                0,  # 17:00
                0,  # 18:00
                0,  # 19:00
                0,  # 20:00
            ],
        )
        self.assertEqual(
            response[1]["days"],
            [
                "2020-01-01 00:00:00",
                "2020-01-01 01:00:00",
                "2020-01-01 02:00:00",
                "2020-01-01 03:00:00",
                "2020-01-01 04:00:00",
                "2020-01-01 05:00:00",
                "2020-01-01 06:00:00",
                "2020-01-01 07:00:00",
                "2020-01-01 08:00:00",
                "2020-01-01 09:00:00",
                "2020-01-01 10:00:00",
                "2020-01-01 11:00:00",
                "2020-01-01 12:00:00",
                "2020-01-01 13:00:00",
                "2020-01-01 14:00:00",
                "2020-01-01 15:00:00",
                "2020-01-01 16:00:00",
                "2020-01-01 17:00:00",
                "2020-01-01 18:00:00",
                "2020-01-01 19:00:00",
                "2020-01-01 20:00:00",
            ],
        )
        self.assertEqual(
            response[1]["data"],
            [
                3,  # 00:00
                0,  # 01:00
                0,  # 02:00
                0,  # 03:00
                0,  # 04:00
                0,  # 05:00
                0,  # 06:00
                0,  # 07:00
                0,  # 08:00
                0,  # 09:00
                0,  # 10:00
                0,  # 11:00
                0,  # 12:00
                0,  # 13:00
                0,  # 14:00
                0,  # 15:00
                0,  # 16:00
                0,  # 17:00
                0,  # 18:00
                0,  # 19:00
                0,  # 20:00
            ],
        )

    def _test_events_with_dates(self, dates: list[str], result, query_time=None, **filter_params):
        self._create_person(team_id=self.team.pk, distinct_ids=["person_1"], properties={"name": "John"})
        for time in dates:
            with freeze_time(time):
                self._create_event(
                    event="event_name",
                    team=self.team,
                    distinct_id="person_1",
                    properties={"$browser": "Safari"},
                )

        if query_time:
            with freeze_time(query_time):
                response = self._run(
                    Filter(
                        team=self.team,
                        data={**filter_params, "events": [{"id": "event_name"}]},
                    ),
                    self.team,
                )
        else:
            response = self._run(
                Filter(
                    team=self.team,
                    data={**filter_params, "events": [{"id": "event_name"}]},
                ),
                self.team,
            )

        self.assertEqual(result[0]["count"], response[0]["count"])
        self.assertEqual(result[0]["labels"], response[0]["labels"])
        self.assertEqual(result[0]["data"], response[0]["data"])
        self.assertEqual(result[0]["days"], response[0]["days"])

        return response

    def test_week_interval(self):
        self._test_events_with_dates(
            dates=["2020-11-01", "2020-11-10", "2020-11-11", "2020-11-18"],
            interval="week",
            date_from="2020-10-29",  # having date after sunday + no events caused an issue in CH
            date_to="2020-11-24",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 4.0,
                    "data": [0.0, 1.0, 2.0, 1.0, 0.0],
                    "labels": [
                        "29–31 Oct",  # starts at the date_from
                        "1–7 Nov",
                        "8–14 Nov",
                        "15–21 Nov",
                        "22–24 Nov",  # ends at the date_to
                    ],
                    "days": [
                        "2020-10-25",
                        "2020-11-01",
                        "2020-11-08",
                        "2020-11-15",
                        "2020-11-22",
                    ],
                }
            ],
        )

    def test_month_interval(self):
        self._test_events_with_dates(
            dates=["2020-07-10", "2020-07-30", "2020-10-18"],
            interval="month",
            date_from="2020-6-01",
            date_to="2020-11-24",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 3.0,
                    "data": [0.0, 2.0, 0.0, 0.0, 1.0, 0.0],
                    "labels": [
                        "Jun 2020",
                        "Jul 2020",
                        "Aug 2020",
                        "Sep 2020",
                        "Oct 2020",
                        "Nov 2020",
                    ],
                    "days": [
                        "2020-06-01",
                        "2020-07-01",
                        "2020-08-01",
                        "2020-09-01",
                        "2020-10-01",
                        "2020-11-01",
                    ],
                }
            ],
        )

    def test_interval_rounding(self):
        self._test_events_with_dates(
            dates=["2020-11-01", "2020-11-10", "2020-11-11", "2020-11-18"],
            interval="week",
            date_from="2020-11-04",
            date_to="2020-11-24",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 3.0,  # includes only events after date_from
                    "data": [0.0, 2.0, 1.0, 0.0],
                    "labels": [
                        "4–7 Nov",
                        "8–14 Nov",
                        "15–21 Nov",
                        "22–24 Nov",
                    ],
                    "days": ["2020-11-01", "2020-11-08", "2020-11-15", "2020-11-22"],
                }
            ],
        )

    def test_interval_rounding_monthly(self):
        self._test_events_with_dates(
            dates=["2020-06-2", "2020-07-30"],
            interval="month",
            date_from="2020-6-7",  # should round down to 6-1
            date_to="2020-7-30",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 2.0,
                    "data": [1.0, 1.0],
                    "labels": ["Jun 2020", "Jul 2020"],
                    "days": ["2020-06-01", "2020-07-01"],
                }
            ],
        )

    def test_today_timerange(self):
        self._test_events_with_dates(
            dates=["2020-11-01 10:20:00", "2020-11-01 10:22:00", "2020-11-01 10:25:00"],
            date_from="dStart",
            query_time="2020-11-01 10:20:00",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 3,
                    "data": [3],
                    "labels": ["1-Nov-2020"],
                    "days": ["2020-11-01"],
                }
            ],
        )

    def test_yesterday_timerange(self):
        self._test_events_with_dates(
            dates=["2020-11-01 05:20:00", "2020-11-01 10:22:00", "2020-11-01 10:25:00"],
            date_from="-1d",
            date_to="-1d",
            query_time="2020-11-02 10:20:00",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 3.0,
                    "data": [3.0],
                    "labels": ["1-Nov-2020"],
                    "days": ["2020-11-01"],
                }
            ],
        )

    def test_last24hours_timerange(self):
        self._test_events_with_dates(
            dates=[
                "2020-11-01 05:20:00",
                "2020-11-01 10:22:00",
                "2020-11-01 10:25:00",
                "2020-11-02 08:25:00",
            ],
            date_from="-24h",
            query_time="2020-11-02 10:20:00",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 3,
                    "data": [2, 1],
                    "labels": ["1-Nov-2020", "2-Nov-2020"],
                    "days": ["2020-11-01", "2020-11-02"],
                }
            ],
        )

    def test_last48hours_timerange(self):
        self._test_events_with_dates(
            dates=[
                "2020-11-01 05:20:00",
                "2020-11-01 10:22:00",
                "2020-11-01 10:25:00",
                "2020-11-02 08:25:00",
            ],
            date_from="-48h",
            query_time="2020-11-02 10:20:00",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 4.0,
                    "data": [0.0, 3.0, 1.0],
                    "labels": ["31-Oct-2020", "1-Nov-2020", "2-Nov-2020"],
                    "days": ["2020-10-31", "2020-11-01", "2020-11-02"],
                }
            ],
        )

    def test_last7days_timerange(self):
        self._test_events_with_dates(
            dates=[
                "2020-11-01 05:20:00",
                "2020-11-02 10:22:00",
                "2020-11-04 10:25:00",
                "2020-11-05 08:25:00",
            ],
            date_from="-7d",
            query_time="2020-11-07 10:20:00",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 4.0,
                    "data": [0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0],
                    "labels": [
                        "31-Oct-2020",
                        "1-Nov-2020",
                        "2-Nov-2020",
                        "3-Nov-2020",
                        "4-Nov-2020",
                        "5-Nov-2020",
                        "6-Nov-2020",
                        "7-Nov-2020",
                    ],
                    "days": [
                        "2020-10-31",
                        "2020-11-01",
                        "2020-11-02",
                        "2020-11-03",
                        "2020-11-04",
                        "2020-11-05",
                        "2020-11-06",
                        "2020-11-07",
                    ],
                }
            ],
        )

    def test_last14days_timerange(self):
        self._test_events_with_dates(
            dates=[
                "2020-11-01 05:20:00",
                "2020-11-02 10:22:00",
                "2020-11-04 10:25:00",
                "2020-11-05 08:25:00",
                "2020-11-05 08:25:00",
                "2020-11-10 08:25:00",
            ],
            date_from="-14d",
            query_time="2020-11-14 10:20:00",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 6.0,
                    "data": [
                        0.0,
                        1.0,
                        1.0,
                        0.0,
                        1.0,
                        2.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        1.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                    ],
                    "labels": [
                        "31-Oct-2020",
                        "1-Nov-2020",
                        "2-Nov-2020",
                        "3-Nov-2020",
                        "4-Nov-2020",
                        "5-Nov-2020",
                        "6-Nov-2020",
                        "7-Nov-2020",
                        "8-Nov-2020",
                        "9-Nov-2020",
                        "10-Nov-2020",
                        "11-Nov-2020",
                        "12-Nov-2020",
                        "13-Nov-2020",
                        "14-Nov-2020",
                    ],
                    "days": [
                        "2020-10-31",
                        "2020-11-01",
                        "2020-11-02",
                        "2020-11-03",
                        "2020-11-04",
                        "2020-11-05",
                        "2020-11-06",
                        "2020-11-07",
                        "2020-11-08",
                        "2020-11-09",
                        "2020-11-10",
                        "2020-11-11",
                        "2020-11-12",
                        "2020-11-13",
                        "2020-11-14",
                    ],
                }
            ],
        )

    def test_last30days_timerange(self):
        self._test_events_with_dates(
            dates=[
                "2020-11-01 05:20:00",
                "2020-11-11 10:22:00",
                "2020-11-24 10:25:00",
                "2020-11-05 08:25:00",
                "2020-11-05 08:25:00",
                "2020-11-10 08:25:00",
            ],
            date_from="-30d",
            interval="week",
            query_time="2020-11-30 10:20:00",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 6.0,
                    "data": [0.0, 3.0, 2.0, 0.0, 1.0, 0.0],
                    "labels": [
                        "31-Oct-2020",
                        "1–7 Nov",
                        "8–14 Nov",
                        "15–21 Nov",
                        "22–28 Nov",
                        "29–30 Nov",
                    ],
                    "days": [
                        "2020-10-25",
                        "2020-11-01",
                        "2020-11-08",
                        "2020-11-15",
                        "2020-11-22",
                        "2020-11-29",
                    ],
                }
            ],
        )

    def test_last90days_timerange(self):
        self._test_events_with_dates(
            dates=[
                "2020-09-01 05:20:00",
                "2020-10-05 05:20:00",
                "2020-10-20 05:20:00",
                "2020-11-01 05:20:00",
                "2020-11-11 10:22:00",
                "2020-11-24 10:25:00",
                "2020-11-05 08:25:00",
                "2020-11-05 08:25:00",
                "2020-11-10 08:25:00",
            ],
            date_from="-90d",
            interval="month",
            query_time="2020-11-30 10:20:00",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 9,
                    "data": [1, 2, 6],
                    "labels": ["Sep 2020", "Oct 2020", "Nov 2020"],
                    "days": ["2020-09-01", "2020-10-01", "2020-11-01"],
                }
            ],
        )

    def test_this_month_timerange(self):
        self._test_events_with_dates(
            dates=[
                "2020-11-01 05:20:00",
                "2020-11-11 10:22:00",
                "2020-11-24 10:25:00",
                "2020-11-05 08:25:00",
                "2020-11-05 08:25:00",
                "2020-11-10 08:25:00",
            ],
            date_from="mStart",
            interval="month",
            query_time="2020-11-30 10:20:00",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 6,
                    "data": [6],
                    "labels": ["Nov 2020"],
                    "days": ["2020-11-01"],
                }
            ],
        )

    def test_previous_month_timerange(self):
        self._test_events_with_dates(
            dates=[
                "2020-11-01 05:20:00",
                "2020-11-11 10:22:00",
                "2020-11-24 10:25:00",
                "2020-11-05 08:25:00",
                "2020-11-05 08:25:00",
                "2020-11-10 08:25:00",
            ],
            date_from="-1mStart",
            date_to="-1mEnd",
            interval="month",
            query_time="2020-12-30 10:20:00",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 6,
                    "data": [6],
                    "labels": ["Nov 2020"],
                    "days": ["2020-11-01"],
                }
            ],
        )

    def test_year_to_date_timerange(self):
        self._test_events_with_dates(
            dates=[
                "2020-01-01 05:20:00",
                "2020-01-11 10:22:00",
                "2020-02-24 10:25:00",
                "2020-02-05 08:25:00",
                "2020-03-05 08:25:00",
                "2020-05-10 08:25:00",
            ],
            date_from="yStart",
            interval="month",
            query_time="2020-04-30 10:20:00",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 5.0,
                    "data": [2.0, 2.0, 1.0, 0.0],
                    "labels": ["Jan 2020", "Feb 2020", "Mar 2020", "Apr 2020"],
                    "days": ["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"],
                }
            ],
        )

    def test_all_time_timerange(self):
        self._test_events_with_dates(
            dates=[
                "2020-01-01 05:20:00",
                "2020-01-11 10:22:00",
                "2020-02-24 10:25:00",
                "2020-02-05 08:25:00",
                "2020-03-05 08:25:00",
            ],
            date_from="all",
            interval="month",
            query_time="2020-04-30 10:20:00",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 5.0,
                    "data": [2.0, 2.0, 1.0, 0.0],
                    "labels": ["Jan 2020", "Feb 2020", "Mar 2020", "Apr 2020"],
                    "days": ["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"],
                }
            ],
        )

    def test_custom_range_timerange(self):
        self._test_events_with_dates(
            dates=[
                "2020-01-05 05:20:00",
                "2020-01-05 10:22:00",
                "2020-01-04 10:25:00",
                "2020-01-11 08:25:00",
                "2020-01-09 08:25:00",
            ],
            date_from="2020-01-05",
            query_time="2020-01-10",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 3.0,
                    "data": [2.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                    "labels": [
                        "5-Jan-2020",
                        "6-Jan-2020",
                        "7-Jan-2020",
                        "8-Jan-2020",
                        "9-Jan-2020",
                        "10-Jan-2020",
                    ],
                    "days": [
                        "2020-01-05",
                        "2020-01-06",
                        "2020-01-07",
                        "2020-01-08",
                        "2020-01-09",
                        "2020-01-10",
                    ],
                }
            ],
        )

    @also_test_with_materialized_columns(["$some_property"])
    def test_property_filtering(self):
        self._create_events()
        with freeze_time("2020-01-04"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "properties": [{"key": "$some_property", "value": "value"}],
                        "events": [{"id": "sign up"}],
                    },
                ),
                self.team,
            )
        self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
        self.assertEqual(response[0]["data"][4], 1.0)
        self.assertEqual(response[0]["labels"][5], "2-Jan-2020")
        self.assertEqual(response[0]["data"][5], 0)

    @snapshot_clickhouse_queries
    def test_trends_with_hogql_math(self):
        s1 = str(uuid7("2020-01-01", 1))
        s5 = str(uuid7("2020-01-01", 5))
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val", "number": 8},
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s1, "x": 1},
            timestamp="2020-01-01 00:06:30",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s5, "x": 5},
            timestamp="2020-01-02 00:06:45",
        )

        with freeze_time("2020-01-04T12:01:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "interval": "week",
                        "events": [
                            {
                                "id": "sign up",
                                "math": "hogql",
                                "math_hogql": "avg(properties.x) + 1000",
                            }
                        ],
                    },
                ),
                self.team,
            )
        self.assertCountEqual(response[0]["labels"], ["28-Dec-2019", "29-Dec-2019 – 4-Jan-2020"])
        self.assertCountEqual(response[0]["data"], [0, 1003])

    @snapshot_clickhouse_queries
    def test_trends_with_session_property_total_volume_math(self):
        s1 = str(uuid7("2020-01-01", 1))
        s2 = str(uuid7("2020-01-01", 2))
        s3 = str(uuid7("2020-01-01", 3))
        s4 = str(uuid7("2020-01-01", 4))
        s5 = str(uuid7("2020-01-01", 5))
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla2"],
            properties={"$some_prop": "some_val"},
        )

        self._create_event(
            team=self.team,
            event="sign up before",
            distinct_id="blabla",
            properties={"$session_id": s1},
            timestamp="2020-01-01 00:06:30",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s1},
            timestamp="2020-01-01 00:06:34",
        )
        self._create_event(
            team=self.team,
            event="sign up later",
            distinct_id="blabla",
            properties={"$session_id": s1},
            timestamp="2020-01-01 00:06:35",
        )
        # First session lasted 5 seconds
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla2",
            properties={"$session_id": s2},
            timestamp="2020-01-01 00:06:35",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla2",
            properties={"$session_id": s2},
            timestamp="2020-01-01 00:06:45",
        )
        # Second session lasted 10 seconds

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s3},
            timestamp="2020-01-01 00:06:45",
        )
        # Third session lasted 0 seconds

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s4},
            timestamp="2020-01-02 00:06:30",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s4},
            timestamp="2020-01-02 00:06:45",
        )
        # Fourth session lasted 15 seconds

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s5},
            timestamp="2020-01-02 00:06:40",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s5},
            timestamp="2020-01-02 00:06:45",
        )
        # Fifth session lasted 5 seconds

        with freeze_time("2020-01-04T13:00:01Z"):
            weekly_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "interval": "week",
                        "events": [
                            {
                                "id": "sign up",
                                "math": "median",
                                "math_property": "$session_duration",
                            }
                        ],
                    },
                ),
                self.team,
            )

        with freeze_time("2020-01-04T13:00:01Z"):
            daily_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "interval": "day",
                        "events": [
                            {
                                "id": "sign up",
                                "math": "median",
                                "math_property": "$session_duration",
                            }
                        ],
                    },
                ),
                self.team,
            )

        self.assertCountEqual(weekly_response[0]["labels"], ["28-Dec-2019", "29-Dec-2019 – 4-Jan-2020"])
        self.assertCountEqual(weekly_response[0]["data"], [0, 5])

        self.assertCountEqual(
            daily_response[0]["labels"],
            [
                "28-Dec-2019",
                "29-Dec-2019",
                "30-Dec-2019",
                "31-Dec-2019",
                "1-Jan-2020",
                "2-Jan-2020",
                "3-Jan-2020",
                "4-Jan-2020",
            ],
        )
        self.assertCountEqual(daily_response[0]["data"], [0, 0, 0, 0, 5, 10, 0, 0])

    @snapshot_clickhouse_queries
    def test_trends_with_session_property_total_volume_math_with_breakdowns(self):
        s1 = str(uuid7("2020-01-01", 1))
        s2 = str(uuid7("2020-01-01", 2))
        s3 = str(uuid7("2020-01-01", 3))
        s4 = str(uuid7("2020-01-01", 4))
        s5 = str(uuid7("2020-01-01", 5))
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla2"],
            properties={"$some_prop": "some_val"},
        )

        self._create_event(
            team=self.team,
            event="sign up before",
            distinct_id="blabla",
            properties={"$session_id": s1, "$some_property": "value1"},
            timestamp="2020-01-01 00:06:30",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s1, "$some_property": "value2"},
            timestamp="2020-01-01 00:06:34",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s1, "$some_property": "value2"},
            timestamp="2020-01-01 00:06:35",
        )
        # First session lasted 5 seconds
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla2",
            properties={"$session_id": s2, "$some_property": "value2"},
            timestamp="2020-01-01 00:06:35",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla2",
            properties={"$session_id": s2, "$some_property": "value1"},
            timestamp="2020-01-01 00:06:45",
        )
        # Second session lasted 10 seconds

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s3, "$some_property": "value1"},
            timestamp="2020-01-01 00:06:45",
        )
        # Third session lasted 0 seconds

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s4, "$some_property": "value2"},
            timestamp="2020-01-02 00:06:30",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s4, "$some_property": "value2"},
            timestamp="2020-01-02 00:06:45",
        )
        # Fourth session lasted 15 seconds

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s5, "$some_property": "value1"},
            timestamp="2020-01-02 00:06:40",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s5, "$some_property": "value1"},
            timestamp="2020-01-02 00:06:45",
        )
        # Fifth session lasted 5 seconds

        for breakdown_type in ("single", "multiple"):
            breakdown_filter: dict[str, Any] = (
                {"breakdown": "$some_property"}
                if breakdown_type == "single"
                else {"breakdowns": [{"property": "$some_property"}]}
            )

            with freeze_time("2020-01-04T13:00:01Z"):
                weekly_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "interval": "week",
                            "events": [
                                {
                                    "id": "sign up",
                                    "math": "median",
                                    "math_property": "$session_duration",
                                }
                            ],
                        },
                    ),
                    self.team,
                )

            with freeze_time("2020-01-04T13:00:05Z"):
                daily_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "interval": "day",
                            "events": [
                                {
                                    "id": "sign up",
                                    "math": "median",
                                    "math_property": "$session_duration",
                                }
                            ],
                        },
                    ),
                    self.team,
                )

            # value1 has 0,5,10 seconds (in second interval)
            # value2 has 5,10,15 seconds (in second interval)
            if breakdown_type == "multiple":
                self.assertEqual(
                    [resp["breakdown_value"] for resp in weekly_response], [["value2"], ["value1"]], breakdown_type
                )
            else:
                self.assertEqual(
                    [resp["breakdown_value"] for resp in weekly_response], ["value2", "value1"], breakdown_type
                )

            self.assertCountEqual(
                weekly_response[0]["labels"], ["28-Dec-2019", "29-Dec-2019 – 4-Jan-2020"], breakdown_type
            )
            self.assertCountEqual(weekly_response[0]["data"], [0, 10], breakdown_type)
            self.assertCountEqual(weekly_response[1]["data"], [0, 5], breakdown_type)

            if breakdown_type == "multiple":
                self.assertEqual(
                    [resp["breakdown_value"] for resp in daily_response], [["value2"], ["value1"]], breakdown_type
                )
            else:
                self.assertEqual(
                    [resp["breakdown_value"] for resp in daily_response], ["value2", "value1"], breakdown_type
                )

            self.assertCountEqual(
                daily_response[0]["labels"],
                [
                    "28-Dec-2019",
                    "29-Dec-2019",
                    "30-Dec-2019",
                    "31-Dec-2019",
                    "1-Jan-2020",
                    "2-Jan-2020",
                    "3-Jan-2020",
                    "4-Jan-2020",
                ],
                breakdown_type,
            )
            self.assertCountEqual(daily_response[0]["data"], [0, 0, 0, 0, 7.5, 15, 0, 0], breakdown_type)
            self.assertCountEqual(daily_response[1]["data"], [0, 0, 0, 0, 5, 5, 0, 0], breakdown_type)

    def test_trends_with_session_property_total_volume_math_with_sessions_spanning_multiple_intervals(self):
        s1 = str(uuid7("2020-01-01", 1))
        s2 = str(uuid7("2020-01-01", 2))
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla2"],
            properties={"$some_prop": "some_val"},
        )

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s1},
            timestamp="2020-01-01 00:06:30",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s1},
            timestamp="2020-01-02 00:06:34",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$session_id": s1},
            timestamp="2020-01-03 00:06:30",
        )
        # First Session lasted 48 hours = a lot of seconds
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla2",
            properties={"$session_id": s2},
            timestamp="2020-01-01 00:06:35",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla2",
            properties={"$session_id": s2},
            timestamp="2020-01-05 00:06:35",
        )
        # Second session lasted 96 hours = a lot of seconds

        with freeze_time("2020-01-06T13:00:01Z"):
            weekly_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "interval": "day",
                        "events": [
                            {
                                "id": "sign up",
                                "math": "median",
                                "math_property": "$session_duration",
                            }
                        ],
                    },
                ),
                self.team,
            )

        self.assertCountEqual(
            weekly_response[0]["labels"],
            [
                "30-Dec-2019",
                "31-Dec-2019",
                "1-Jan-2020",
                "2-Jan-2020",
                "3-Jan-2020",
                "4-Jan-2020",
                "5-Jan-2020",
                "6-Jan-2020",
            ],
        )

        ONE_DAY_IN_SECONDS = 24 * 60 * 60
        # math property is counted only in the intervals in which the session was active
        # and the event in question happened (i.e. sign up event)
        self.assertCountEqual(
            weekly_response[0]["data"],
            [
                0,
                0,
                3 * ONE_DAY_IN_SECONDS,
                2 * ONE_DAY_IN_SECONDS,
                2 * ONE_DAY_IN_SECONDS,
                0,
                4 * ONE_DAY_IN_SECONDS,
                0,
            ],
        )

    @also_test_with_person_on_events_v2
    @also_test_with_materialized_columns(person_properties=["name"])
    def test_filter_events_by_cohort(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["person_1"], properties={"name": "John"})
        self._create_person(team_id=self.team.pk, distinct_ids=["person_2"], properties={"name": "Jane"})

        self._create_event(
            event="event_name",
            team=self.team,
            distinct_id="person_1",
            properties={"$browser": "Safari"},
        )
        self._create_event(
            event="event_name",
            team=self.team,
            distinct_id="person_2",
            properties={"$browser": "Chrome"},
        )
        self._create_event(
            event="event_name",
            team=self.team,
            distinct_id="person_2",
            properties={"$browser": "Safari"},
        )

        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "Jane", "type": "person"}]}],
        )

        response = self._run(
            Filter(
                team=self.team,
                data={
                    "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                    "events": [{"id": "event_name"}],
                },
            ),
            self.team,
        )

        self.assertEqual(response[0]["count"], 2)
        self.assertEqual(response[0]["data"][-1], 2)

    @also_test_with_person_on_events_v2
    @snapshot_clickhouse_queries
    def test_filter_events_by_precalculated_cohort(self):
        with freeze_time("2020-01-02"):
            self._create_person(
                team_id=self.team.pk,
                distinct_ids=["person_1"],
                properties={"name": "John"},
            )
            self._create_person(
                team_id=self.team.pk,
                distinct_ids=["person_2"],
                properties={"name": "Jane"},
            )

            self._create_event(
                event="event_name",
                team=self.team,
                distinct_id="person_1",
                properties={"$browser": "Safari"},
            )
            self._create_event(
                event="event_name",
                team=self.team,
                distinct_id="person_2",
                properties={"$browser": "Chrome"},
            )
            self._create_event(
                event="event_name",
                team=self.team,
                distinct_id="person_2",
                properties={"$browser": "Safari"},
            )

            cohort = _create_cohort(
                team=self.team,
                name="cohort1",
                groups=[{"properties": [{"key": "name", "value": "Jane", "type": "person"}]}],
            )
            cohort.calculate_people_ch(pending_version=0)

            with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
                response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                            "events": [{"id": "event_name"}],
                        },
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["count"], 2)
            self.assertEqual(response[0]["data"][-1], 2)

    def test_response_empty_if_no_events(self):
        self._create_events()
        flush_persons_and_events()
        response = self._run(Filter(team=self.team, data={"date_from": "2012-12-12"}), self.team)
        self.assertEqual(response, [])

    def test_interval_filtering_hour(self):
        self._create_events(use_time=True)

        with freeze_time("2020-01-02"):
            response = self._run(
                Filter(
                    data={
                        "date_from": "2019-12-24",
                        "interval": "hour",
                        "events": [{"id": "sign up"}],
                    }
                ),
                self.team,
            )
        self.assertEqual(response[0]["labels"][3], "24-Dec 03:00")
        self.assertEqual(response[0]["data"][3], 1.0)
        # 217 - 24 - 1
        self.assertEqual(response[0]["data"][192], 3.0)

    def test_interval_filtering_week(self):
        self._create_events(use_time=True)

        with freeze_time("2020-01-02"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        #  2019-11-24 is a Sunday, i.e. beginning of our week
                        "date_from": "2019-11-24",
                        "interval": "week",
                        "events": [{"id": "sign up"}],
                    },
                ),
                self.team,
            )
        self.assertEqual(
            response[0]["labels"][:5],
            ["24–30 Nov", "1–7 Dec", "8–14 Dec", "15–21 Dec", "22–28 Dec"],
        )
        self.assertEqual(response[0]["data"][:5], [0.0, 0.0, 0.0, 0.0, 1.0])

    def test_interval_filtering_month(self):
        self._create_events(use_time=True)

        with freeze_time("2020-01-02"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "2019-9-24",
                        "interval": "month",
                        "events": [{"id": "sign up"}],
                    },
                ),
                self.team,
            )
        self.assertEqual(response[0]["labels"][0], "Sep 2019")
        self.assertEqual(response[0]["data"][0], 0)
        self.assertEqual(response[0]["labels"][3], "Dec 2019")
        self.assertEqual(response[0]["data"][3], 1.0)
        self.assertEqual(response[0]["labels"][4], "Jan 2020")
        self.assertEqual(response[0]["data"][4], 4.0)

    def test_interval_filtering_today_hourly(self):
        self._create_events(use_time=True)

        with freeze_time("2020-01-02 23:30"):
            self._create_event(team=self.team, event="sign up", distinct_id="blabla")

        with freeze_time("2020-01-02T23:31:00Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "dStart",
                        "interval": "hour",
                        "events": [{"id": "sign up"}],
                    },
                ),
                self.team,
            )
        self.assertEqual(response[0]["labels"][23], "2-Jan 23:00")
        self.assertEqual(response[0]["data"][23], 1.0)

    def test_breakdown_label(self):
        entity = Entity({"id": "$pageview", "name": "$pageview", "type": TREND_FILTER_TYPE_EVENTS})
        num_label = breakdown_label(entity, 1)
        self.assertEqual(num_label, {"label": "$pageview - 1", "breakdown_value": 1})

        string_label = breakdown_label(entity, "Chrome")
        self.assertEqual(string_label, {"label": "$pageview - Chrome", "breakdown_value": "Chrome"})

        nan_label = breakdown_label(entity, "nan")
        self.assertEqual(nan_label, {"label": "$pageview - Other", "breakdown_value": "Other"})

        none_label = breakdown_label(entity, "None")
        self.assertEqual(none_label, {"label": "$pageview - Other", "breakdown_value": "Other"})

        cohort_all_label = breakdown_label(entity, "cohort_all")
        self.assertEqual(
            cohort_all_label,
            {"label": "$pageview - all users", "breakdown_value": "all"},
        )

        cohort = _create_cohort(team=self.team, name="cohort1", groups=[{"properties": {"name": "Jane"}}])
        cohort_label = breakdown_label(entity, f"cohort_{cohort.pk}")
        self.assertEqual(
            cohort_label,
            {"label": f"$pageview - {cohort.name}", "breakdown_value": cohort.pk},
        )

    @also_test_with_materialized_columns(["key"])
    def test_breakdown_with_filter(self):
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"email": "test@posthog.com"},
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"email": "test@gmail.com"},
        )
        self._create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "val"},
        )
        self._create_event(
            event="sign up",
            distinct_id="person2",
            team=self.team,
            properties={"key": "oh"},
        )
        response = self._run(
            Filter(
                team=self.team,
                data={
                    "date_from": "-14d",
                    "breakdown": "key",
                    "events": [
                        {
                            "id": "sign up",
                            "name": "sign up",
                            "type": "events",
                            "order": 0,
                        }
                    ],
                    "properties": [{"key": "key", "value": "oh", "operator": "not_icontains"}],
                },
            ),
            self.team,
        )
        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]["breakdown_value"], "val")

    def test_action_filtering(self):
        sign_up_action, person = self._create_events()
        action_response = self._run(
            Filter(team=self.team, data={"actions": [{"id": sign_up_action.id}]}),
            self.team,
        )
        event_response = self._run(Filter(team=self.team, data={"events": [{"id": "sign up"}]}), self.team)
        self.assertEqual(len(action_response), 1)

        self.assertEntityResponseEqual(action_response, event_response)

    def test_action_filtering_for_action_in_different_env_of_project(self):
        sign_up_action, person = self._create_events()
        other_team_in_project = Team.objects.create(organization=self.organization, project=self.project)
        sign_up_action.team = other_team_in_project
        sign_up_action.save()

        action_response = self._run(
            Filter(team=self.team, data={"actions": [{"id": sign_up_action.id}]}),
            self.team,
        )
        event_response = self._run(Filter(team=self.team, data={"events": [{"id": "sign up"}]}), self.team)
        self.assertEqual(len(action_response), 1)

        self.assertEntityResponseEqual(action_response, event_response)

    @also_test_with_person_on_events_v2
    @snapshot_clickhouse_queries
    def test_action_filtering_with_cohort(self):
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_property": "value", "$bool_prop": "x"},
        )
        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "$some_property", "value": "value", "type": "person"}]}],
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$some_property": "value"},
            timestamp="2020-01-02T12:00:00Z",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={"$some_property": "value2"},
            timestamp="2020-01-03T12:00:00Z",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="xyz",
            properties={"$some_property": "value"},
            timestamp="2020-01-04T12:00:00Z",
        )

        sign_up_action = _create_action(
            team=self.team,
            name="sign up",
            properties=[{"key": "id", "type": "cohort", "value": cohort.id}],
        )

        cohort.calculate_people_ch(pending_version=2)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            action_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "actions": [{"id": sign_up_action.id}],
                        "date_from": "2020-01-01",
                        "date_to": "2020-01-07",
                        "properties": [{"key": "$bool_prop", "value": "x", "type": "person"}],
                    },
                ),
                self.team,
            )
            self.assertEqual(len(action_response), 1)
            self.assertEqual(action_response[0]["data"], [0, 1, 1, 0, 0, 0, 0])

    def test_trends_for_non_existing_action(self):
        with freeze_time("2020-01-04"):
            response = self._run(Filter(data={"actions": [{"id": 50000000}]}), self.team)
        self.assertEqual(len(response), 0)

        with freeze_time("2020-01-04"):
            response = self._run(Filter(data={"events": [{"id": "DNE"}]}), self.team)
        self.assertEqual(response[0]["data"], [0, 0, 0, 0, 0, 0, 0, 0])

    @also_test_with_materialized_columns(person_properties=["email", "bar"])
    def test_trends_regression_filtering_by_action_with_person_properties(self):
        self._create_person(
            team_id=self.team.pk,
            properties={"email": "foo@example.com", "bar": "aa"},
            distinct_ids=["d1"],
        )
        self._create_person(
            team_id=self.team.pk,
            properties={"email": "bar@example.com", "bar": "bb"},
            distinct_ids=["d2"],
        )
        self._create_person(
            team_id=self.team.pk,
            properties={"email": "efg@example.com", "bar": "ab"},
            distinct_ids=["d3"],
        )
        self._create_person(team_id=self.team.pk, properties={"bar": "aa"}, distinct_ids=["d4"])

        with freeze_time("2020-01-02 16:34:34"):
            self._create_event(team=self.team, event="$pageview", distinct_id="d1")
            self._create_event(team=self.team, event="$pageview", distinct_id="d2")
            self._create_event(team=self.team, event="$pageview", distinct_id="d3")
            self._create_event(team=self.team, event="$pageview", distinct_id="d4")

        event_filtering_action = Action.objects.create(
            team=self.team,
            name="$pageview from non-internal",
            steps_json=[
                {
                    "event": "$pageview",
                    "properties": [{"key": "bar", "type": "person", "value": "a", "operator": "icontains"}],
                }
            ],
        )

        with freeze_time("2020-01-04T13:01:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={"actions": [{"id": event_filtering_action.id}]},
                ),
                self.team,
            )
        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]["count"], 3)

        with freeze_time("2020-01-04T13:01:01Z"):
            response_with_email_filter = self._run(
                Filter(
                    team=self.team,
                    data={
                        "actions": [{"id": event_filtering_action.id}],
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "is_set",
                                "operator": "is_set",
                            }
                        ],
                    },
                ),
                self.team,
            )
        self.assertEqual(len(response_with_email_filter), 1)
        self.assertEqual(response_with_email_filter[0]["count"], 2)

    def test_dau_filtering(self):
        sign_up_action, person = self._create_events()

        with freeze_time("2020-01-02"):
            self._create_person(team_id=self.team.pk, distinct_ids=["someone_else"])
            self._create_event(team=self.team, event="sign up", distinct_id="someone_else")

        with freeze_time("2020-01-04"):
            action_response = self._run(
                Filter(
                    team=self.team,
                    data={"actions": [{"id": sign_up_action.id, "math": "dau"}]},
                ),
                self.team,
            )
            response = self._run(Filter(data={"events": [{"id": "sign up", "math": "dau"}]}), self.team)

        self.assertEqual(response[0]["data"][4], 1)
        self.assertEqual(response[0]["data"][5], 2)
        self.assertEntityResponseEqual(action_response, response)

    def _create_maths_events(self, values):
        sign_up_action, person = self._create_events()
        self._create_person(team_id=self.team.pk, distinct_ids=["someone_else"])
        for value in values:
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="someone_else",
                properties={"some_number": value},
            )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="someone_else",
            properties={"some_number": None},
        )
        return sign_up_action

    def _test_math_property_aggregation(self, math_property, values, expected_value):
        sign_up_action = self._create_maths_events(values)

        action_response = self._run(
            Filter(
                team=self.team,
                data={
                    "actions": [
                        {
                            "id": sign_up_action.id,
                            "math": math_property,
                            "math_property": "some_number",
                        }
                    ]
                },
            ),
            self.team,
        )
        event_response = self._run(
            Filter(
                data={
                    "events": [
                        {
                            "id": "sign up",
                            "math": math_property,
                            "math_property": "some_number",
                        }
                    ]
                }
            ),
            self.team,
        )
        # :TRICKY: Work around clickhouse functions not being 100%
        self.assertAlmostEqual(action_response[0]["data"][-1], expected_value, delta=0.5)
        self.assertEntityResponseEqual(action_response, event_response)

    @also_test_with_materialized_columns(["some_number"])
    def test_sum_filtering(self):
        self._test_math_property_aggregation("sum", values=[2, 3, 5.5, 7.5], expected_value=18)

    @also_test_with_materialized_columns(["some_number"])
    def test_avg_filtering(self):
        self._test_math_property_aggregation("avg", values=[2, 3, 5.5, 7.5], expected_value=4.5)

    @also_test_with_materialized_columns(["some_number"])
    def test_min_filtering(self):
        self._test_math_property_aggregation("min", values=[2, 3, 5.5, 7.5], expected_value=2)

    @also_test_with_materialized_columns(["some_number"])
    def test_max_filtering(self):
        self._test_math_property_aggregation("max", values=[2, 3, 5.5, 7.5], expected_value=7.5)

    @also_test_with_materialized_columns(["some_number"])
    def test_median_filtering(self):
        self._test_math_property_aggregation("median", values=range(101, 201), expected_value=150)

    @also_test_with_materialized_columns(["some_number"])
    def test_p75_filtering(self):
        self._test_math_property_aggregation("p75", values=range(101, 201), expected_value=175)

    @also_test_with_materialized_columns(["some_number"])
    def test_p90_filtering(self):
        self._test_math_property_aggregation("p90", values=range(101, 201), expected_value=190)

    @also_test_with_materialized_columns(["some_number"])
    def test_p95_filtering(self):
        self._test_math_property_aggregation("p95", values=range(101, 201), expected_value=195)

    @also_test_with_materialized_columns(["some_number"])
    def test_p99_filtering(self):
        self._test_math_property_aggregation("p99", values=range(101, 201), expected_value=199)

    @also_test_with_materialized_columns(["some_number"])
    def test_avg_filtering_non_number_resiliency(self):
        sign_up_action, person = self._create_events()
        self._create_person(team_id=self.team.pk, distinct_ids=["someone_else"])
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="someone_else",
            properties={"some_number": 2},
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="someone_else",
            properties={"some_number": "x"},
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="someone_else",
            properties={"some_number": None},
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="someone_else",
            properties={"some_number": 8},
        )
        action_response = self._run(
            Filter(
                data={
                    "actions": [
                        {
                            "id": sign_up_action.id,
                            "math": "avg",
                            "math_property": "some_number",
                        }
                    ]
                }
            ),
            self.team,
        )
        event_response = self._run(
            Filter(data={"events": [{"id": "sign up", "math": "avg", "math_property": "some_number"}]}),
            self.team,
        )
        self.assertEqual(action_response[0]["data"][-1], 5)
        self.assertEntityResponseEqual(action_response, event_response)

    @also_test_with_materialized_columns(["$some_property"])
    def test_per_entity_filtering(self):
        self._create_events()
        with freeze_time("2020-01-04T13:00:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-7d",
                        "events": [
                            {
                                "id": "sign up",
                                "properties": [{"key": "$some_property", "value": "value"}],
                            },
                            {
                                "id": "sign up",
                                "properties": [{"key": "$some_property", "value": "other_value"}],
                            },
                        ],
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
        self.assertEqual(response[0]["data"][4], 1)
        self.assertEqual(response[0]["count"], 1)
        self.assertEqual(response[1]["labels"][5], "2-Jan-2020")
        self.assertEqual(response[1]["data"][5], 1)
        self.assertEqual(response[1]["count"], 1)

    def _create_multiple_people(self):
        person1 = self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"name": "person1"},
        )
        person2 = self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"name": "person2"},
        )
        person3 = self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person3"],
            properties={"name": "person3"},
        )
        person4 = self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person4"],
            properties={"name": "person4"},
        )

        journey = {
            "person1": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 1, 12),
                    "properties": {"order": "1", "name": "1"},
                }
            ],
            "person2": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 1, 12),
                    "properties": {"order": "1", "name": "2"},
                },
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12),
                    "properties": {"order": "2", "name": "2"},
                },
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12),
                    "properties": {"order": "2", "name": "2"},
                },
            ],
            "person3": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 1, 12),
                    "properties": {"order": "1", "name": "3"},
                },
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 2, 12),
                    "properties": {"order": "2", "name": "3"},
                },
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 3, 12),
                    "properties": {"order": "2", "name": "3"},
                },
            ],
            "person4": [
                {
                    "event": "watched movie",
                    "timestamp": datetime(2020, 1, 5, 12),
                    "properties": {"order": "1", "name": "4"},
                }
            ],
        }

        journeys_for(events_by_person=journey, team=self.team)

        for key in ["order", "name"]:
            exists = PropertyDefinition.objects.filter(team=self.team, name=key).exists()
            if not exists:
                PropertyDefinition.objects.create(
                    team=self.team,
                    name=key,
                    property_type="String",
                    type=PropertyDefinition.Type.EVENT,
                )

        return (person1, person2, person3, person4)

    @also_test_with_materialized_columns(person_properties=["name"])
    @snapshot_clickhouse_queries
    def test_person_property_filtering(self):
        self._create_multiple_people()
        with freeze_time("2020-01-04"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "properties": [{"key": "name", "value": "person1", "type": "person"}],
                        "events": [{"id": "watched movie"}],
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
        self.assertEqual(response[0]["data"][4], 1.0)
        self.assertEqual(response[0]["labels"][5], "2-Jan-2020")
        self.assertEqual(response[0]["data"][5], 0)

    @also_test_with_materialized_columns(["name"], person_properties=["name"])
    @snapshot_clickhouse_queries
    def test_person_property_filtering_clashing_with_event_property(self):
        # This test needs to choose the right materialised column for it to pass.
        # For resiliency, we reverse the filter as well.
        self._create_multiple_people()
        with freeze_time("2020-01-04"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "properties": [{"key": "name", "value": "person1", "type": "person"}],
                        "events": [{"id": "watched movie"}],
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
        self.assertEqual(response[0]["data"][4], 1.0)
        self.assertEqual(response[0]["labels"][5], "2-Jan-2020")
        self.assertEqual(response[0]["data"][5], 0)

        with freeze_time("2020-01-04"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "properties": [{"key": "name", "value": "1", "type": "event"}],
                        "events": [{"id": "watched movie"}],
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
        self.assertEqual(response[0]["data"][4], 1.0)
        self.assertEqual(response[0]["labels"][5], "2-Jan-2020")
        self.assertEqual(response[0]["data"][5], 0)

    @also_test_with_materialized_columns(person_properties=["name"])
    def test_entity_person_property_filtering(self):
        self._create_multiple_people()
        with freeze_time("2020-01-04"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "events": [
                            {
                                "id": "watched movie",
                                "properties": [
                                    {
                                        "key": "name",
                                        "value": "person1",
                                        "type": "person",
                                    }
                                ],
                            }
                        ]
                    },
                ),
                self.team,
            )
        self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
        self.assertEqual(response[0]["data"][4], 1.0)
        self.assertEqual(response[0]["labels"][5], "2-Jan-2020")
        self.assertEqual(response[0]["data"][5], 0)

    def test_breakdown_by_empty_cohort(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-04T12:00:00Z",
        )

        with freeze_time("2020-01-04T13:01:01Z"):
            event_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdown": json.dumps(["all"]),
                        "breakdown_type": "cohort",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                    },
                ),
                self.team,
            )

        self.assertEqual(event_response[0]["label"], "all users")
        self.assertEqual(sum(event_response[0]["data"]), 1)

    @also_test_with_person_on_events_v2
    @also_test_with_materialized_columns(person_properties=["name"], verify_no_jsonextract=False)
    def test_breakdown_by_cohort(self):
        person1, person2, person3, person4 = self._create_multiple_people()
        cohort = _create_cohort(
            name="cohort1",
            team=self.team,
            groups=[{"properties": [{"key": "name", "value": "person1", "type": "person"}]}],
        )
        cohort2 = _create_cohort(
            name="cohort2",
            team=self.team,
            groups=[{"properties": [{"key": "name", "value": "person2", "type": "person"}]}],
        )
        cohort3 = _create_cohort(
            name="cohort3",
            team=self.team,
            groups=[
                {"properties": [{"key": "name", "value": "person1", "type": "person"}]},
                {"properties": [{"key": "name", "value": "person2", "type": "person"}]},
            ],
        )
        action = _create_action(name="watched movie", team=self.team)

        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdown": json.dumps([cohort.pk, cohort2.pk, cohort3.pk, "all"]),
                        "breakdown_type": "cohort",
                        "actions": [{"id": action.pk, "type": "actions", "order": 0}],
                    },
                ),
                self.team,
            )
            event_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdown": json.dumps([cohort.pk, cohort2.pk, cohort3.pk, "all"]),
                        "breakdown_type": "cohort",
                        "events": [
                            {
                                "id": "watched movie",
                                "name": "watched movie",
                                "type": "events",
                                "order": 0,
                            }
                        ],
                    },
                ),
                self.team,
            )

        counts = {}
        break_val = {}
        for res in event_response:
            counts[res["label"]] = sum(res["data"])
            break_val[res["label"]] = res["breakdown_value"]

        self.assertEqual(counts["watched movie - cohort1"], 1)
        self.assertEqual(counts["watched movie - cohort2"], 3)
        self.assertEqual(counts["watched movie - cohort3"], 4)
        self.assertEqual(counts["watched movie - all users"], 7)

        self.assertEqual(break_val["watched movie - cohort1"], cohort.pk)
        self.assertEqual(break_val["watched movie - cohort2"], cohort2.pk)
        self.assertEqual(break_val["watched movie - cohort3"], cohort3.pk)
        self.assertEqual(break_val["watched movie - all users"], "all")

        self.assertEntityResponseEqual(event_response, action_response)

    def test_breakdown_by_event_metadata(self):
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-04T12:00:00Z",
        )
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-04T12:00:00Z",
        )
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-04T12:00:00Z",
        )

        with freeze_time("2020-01-04T13:01:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-7d",
                        "interval": "hour",
                        "events": [{"id": "$pageview"}],
                        "breakdown": "distinct_id",
                        "breakdown_type": "event_metadata",
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["label"], "p1")
        self.assertEqual(response[1]["label"], "p2")
        self.assertEqual(response[0]["count"], 2)
        self.assertEqual(response[1]["count"], 1)

    @also_test_with_materialized_columns(verify_no_jsonextract=False)
    def test_interval_filtering_breakdown(self):
        self._create_events(use_time=True)
        cohort = _create_cohort(
            name="cohort1",
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "some_val", "type": "person"}]}],
        )

        # test hour
        with freeze_time("2020-01-02"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "2019-12-24",
                        "interval": "hour",
                        "events": [{"id": "sign up"}],
                        "breakdown": json.dumps([cohort.pk]),
                        "breakdown_type": "cohort",
                    },
                ),
                self.team,
            )
        self.assertEqual(response[0]["labels"][3], "24-Dec 03:00")
        self.assertEqual(response[0]["data"][3], 1.0)
        # 217 - 24 - 1
        self.assertEqual(response[0]["data"][192], 3.0)

        # test week
        with freeze_time("2020-01-02"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        # 2019-11-24 is a Sunday
                        "date_from": "2019-11-24",
                        "interval": "week",
                        "events": [{"id": "sign up"}],
                        "breakdown": json.dumps([cohort.pk]),
                        "breakdown_type": "cohort",
                    },
                ),
                self.team,
            )

        self.assertEqual(
            response[0]["labels"][:5],
            ["24–30 Nov", "1–7 Dec", "8–14 Dec", "15–21 Dec", "22–28 Dec"],
        )
        self.assertEqual(response[0]["data"][:5], [0.0, 0.0, 0.0, 0.0, 1.0])

        # test month
        with freeze_time("2020-01-02"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "2019-9-24",
                        "interval": "month",
                        "events": [{"id": "sign up"}],
                        "breakdown": json.dumps([cohort.pk]),
                        "breakdown_type": "cohort",
                    },
                ),
                self.team,
            )
        self.assertEqual(response[0]["labels"][3], "Dec 2019")
        self.assertEqual(response[0]["data"][3], 1.0)
        self.assertEqual(response[0]["labels"][4], "Jan 2020")
        self.assertEqual(response[0]["data"][4], 4.0)

        with freeze_time("2020-01-02 23:30"):
            self._create_event(team=self.team, event="sign up", distinct_id="blabla")

        # test today + hourly
        with freeze_time("2020-01-02T23:31:00Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "dStart",
                        "interval": "hour",
                        "events": [{"id": "sign up"}],
                        "breakdown": json.dumps([cohort.pk]),
                        "breakdown_type": "cohort",
                    },
                ),
                self.team,
            )
        self.assertEqual(response[0]["labels"][23], "2-Jan 23:00")
        self.assertEqual(response[0]["data"][23], 1.0)

    def test_breakdown_by_person_property(self):
        person1, person2, person3, person4 = self._create_multiple_people()
        action = _create_action(name="watched movie", team=self.team)

        for breakdown_type in ("single", "multiple"):
            breakdown_filter: dict[str, Any] = (
                {
                    "breakdowns": [
                        {
                            "type": "person",
                            "property": "name",
                        }
                    ]
                }
                if breakdown_type == "multiple"
                else {
                    "breakdown": "name",
                    "breakdown_type": "person",
                }
            )

            with freeze_time("2020-01-04T13:01:01Z"):
                action_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "date_from": "-14d",
                            "actions": [{"id": action.pk, "type": "actions", "order": 0}],
                        },
                    ),
                    self.team,
                )
                event_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "date_from": "-14d",
                            "events": [
                                {
                                    "id": "watched movie",
                                    "name": "watched movie",
                                    "type": "events",
                                    "order": 0,
                                }
                            ],
                        },
                    ),
                    self.team,
                )

            if breakdown_type == "multiple":
                self.assertListEqual(
                    sorted(res["breakdown_value"] for res in event_response),
                    [["person1"], ["person2"], ["person3"]],
                )
            else:
                self.assertListEqual(
                    sorted(res["breakdown_value"] for res in event_response),
                    ["person1", "person2", "person3"],
                )

            for response in event_response:
                if breakdown_type == "multiple":
                    if response["breakdown_value"] == ("person1"):
                        self.assertEqual(response["count"], 1)
                        self.assertEqual(response["label"], ["person1"])
                else:
                    if response["breakdown_value"] == "person1":
                        self.assertEqual(response["count"], 1)
                        self.assertEqual(response["label"], "person1")

                if response["breakdown_value"] == "person2":
                    self.assertEqual(response["count"], 3)
                if response["breakdown_value"] == "person3":
                    self.assertEqual(response["count"], 3)

            self.assertEntityResponseEqual(event_response, action_response)

    def test_virtual_person_property_breakdown(self):
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"$initial_referring_domain": "https://www.google.com"},
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"$initial_referring_domain": "$direct"},
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person3"],
            properties={"$initial_referring_domain": "https://www.someothersite.com"},
        )

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="person1",
            timestamp="2020-01-04T12:00:00Z",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="person2",
            timestamp="2020-01-04T12:00:00Z",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="person3",
            timestamp="2020-01-04T12:00:00Z",
        )

        with freeze_time("2020-01-04T13:01:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-7d",
                        "events": [{"id": "sign up"}],
                        "breakdown": "$virt_initial_channel_type",
                        "breakdown_type": "person",
                    },
                ),
                self.team,
            )

        assert len(response) == 3
        assert response[0]["label"] == "Direct"
        assert response[1]["label"] == "Organic Search"
        assert response[2]["label"] == "Referral"
        assert response[0]["count"] == 1
        assert response[1]["count"] == 1
        assert response[2]["count"] == 1

    @also_test_with_materialized_columns(["name"], person_properties=["name"])
    def test_breakdown_by_person_property_for_person_on_events(self):
        person1, person2, person3, person4 = self._create_multiple_people()

        # single breakdown
        with freeze_time("2020-01-04T13:01:01Z"):
            event_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdown": "name",
                        "breakdown_type": "person",
                        "events": [
                            {
                                "id": "watched movie",
                                "name": "watched movie",
                                "type": "events",
                                "order": 0,
                            }
                        ],
                    },
                ),
                self.team,
            )

        self.assertListEqual(
            sorted(res["breakdown_value"] for res in event_response),
            ["person1", "person2", "person3"],
        )

        for response in event_response:
            if response["breakdown_value"] == "person1":
                self.assertEqual(response["count"], 1)
                self.assertEqual(response["label"], "person1")
            if response["breakdown_value"] == "person2":
                self.assertEqual(response["count"], 3)
            if response["breakdown_value"] == "person3":
                self.assertEqual(response["count"], 3)

        # multiple breakdowns
        with freeze_time("2020-01-04T13:01:01Z"):
            event_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdowns": [
                            {
                                "property": "name",
                                "type": "person",
                            }
                        ],
                        "events": [
                            {
                                "id": "watched movie",
                                "name": "watched movie",
                                "type": "events",
                                "order": 0,
                            }
                        ],
                    },
                ),
                self.team,
            )

        self.assertListEqual(
            sorted(res["breakdown_value"] for res in event_response),
            [["person1"], ["person2"], ["person3"]],
        )

        for response in event_response:
            if response["breakdown_value"] == ["person1"]:
                self.assertEqual(response["count"], 1)
                self.assertEqual(response["label"], "person1")
            if response["breakdown_value"] == "person2":
                self.assertEqual(response["count"], 3)
            if response["breakdown_value"] == "person3":
                self.assertEqual(response["count"], 3)

    def test_breakdown_by_person_property_for_person_on_events_with_zero_person_ids(self):
        # only a person-on-event test
        if not get_instance_setting("PERSON_ON_EVENTS_ENABLED"):
            return True

        self._create_multiple_people()

        self._create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person5",
            person_id="00000000-0000-0000-0000-000000000000",
            person_properties={"name": "person5"},
            timestamp=datetime(2020, 1, 1, 12),
        )
        self._create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person6",
            person_id="00000000-0000-0000-0000-000000000000",
            person_properties={"name": "person6"},
            timestamp=datetime(2020, 1, 1, 12),
        )
        self._create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person7",
            person_id="00000000-0000-0000-0000-000000000000",
            person_properties={"name": "person2"},
            timestamp=datetime(2020, 1, 1, 12),
        )

        with freeze_time("2020-01-04T13:01:01Z"):
            event_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdown": "name",
                        "breakdown_type": "person",
                        "events": [
                            {
                                "id": "watched movie",
                                "name": "watched movie",
                                "type": "events",
                                "order": 0,
                            }
                        ],
                    },
                ),
                self.team,
            )

        self.assertListEqual(
            sorted(res["breakdown_value"] for res in event_response),
            ["person1", "person2", "person3"],
        )

        for response in event_response:
            if response["breakdown_value"] == "person1":
                self.assertEqual(response["count"], 1)
                self.assertEqual(response["label"], "person1")
            if response["breakdown_value"] == "person2":
                self.assertEqual(response["count"], 3)
            if response["breakdown_value"] == "person3":
                self.assertEqual(response["count"], 3)

        with freeze_time("2020-01-04T13:01:01Z"):
            event_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdowns": [
                            {
                                "property": "name",
                                "type": "person",
                            }
                        ],
                        "events": [
                            {
                                "id": "watched movie",
                                "name": "watched movie",
                                "type": "events",
                                "order": 0,
                            }
                        ],
                    },
                ),
                self.team,
            )

        self.assertListEqual(
            sorted(res["breakdown_value"] for res in event_response),
            [["person1"], ["person2"], ["person3"]],
        )

        for response in event_response:
            if response["breakdown_value"] == ["person1"]:
                self.assertEqual(response["count"], 1)
                self.assertEqual(response["label"], ["person1"])
            if response["breakdown_value"] == "person2":
                self.assertEqual(response["count"], 3)
            if response["breakdown_value"] == "person3":
                self.assertEqual(response["count"], 3)

    def test_breakdown_by_property_pie(self):
        with freeze_time("2020-01-01T12:00:00Z"):  # Fake created_at for easier assertions
            self._create_person(team_id=self.team.pk, distinct_ids=["person1"], immediate=True)
            self._create_person(team_id=self.team.pk, distinct_ids=["person2"], immediate=True)
            self._create_person(team_id=self.team.pk, distinct_ids=["person3"], immediate=True)

        self._create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person1",
            timestamp="2020-01-01T12:00:00Z",
            properties={"fake_prop": "value_1"},
        )

        self._create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person2",
            timestamp="2020-01-01T12:00:00Z",
            properties={"fake_prop": "value_1"},
        )
        self._create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person2",
            timestamp="2020-01-01T12:00:00Z",
            properties={"fake_prop": "value_1"},
        )
        self._create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person2",
            timestamp="2020-01-02T12:00:00Z",
            properties={"fake_prop": "value_2"},
        )

        self._create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person3",
            timestamp="2020-01-01T12:00:00Z",
            properties={"fake_prop": "value_1"},
        )

        self._create_person(team_id=self.team.pk, distinct_ids=["person4"], immediate=True)
        self._create_event(
            team=self.team,
            event="watched movie",
            distinct_id="person4",
            timestamp="2020-01-05T12:00:00Z",
            properties={"fake_prop": "value_1"},
        )

        with freeze_time("2020-01-04T13:01:01Z"):
            filters = {
                "date_from": "-14d",
                "breakdown": "fake_prop",
                "breakdown_type": "event",
                "display": "ActionsPie",
                "events": [
                    {
                        "id": "watched movie",
                        "name": "watched movie",
                        "type": "events",
                        "order": 0,
                        "math": "dau",
                    }
                ],
            }
            event_response = self._run(Filter(team=self.team, data=filters), self.team)
            event_response = sorted(event_response, key=lambda resp: resp["breakdown_value"])

            people_value_1 = self._get_actors(
                filters=filters, team=self.team, series=0, breakdown="value_1", includeRecordings=True
            )
            # Persons with higher value come first
            self.assertEqual(people_value_1[0][0]["distinct_ids"][0], "person2")
            self.assertEqual(people_value_1[0][2], 2)  # 2 events with fake_prop="value_1" in the time range
            self.assertEqual(people_value_1[1][2], 1)  # 1 event with fake_prop="value_1" in the time range
            self.assertEqual(people_value_1[2][2], 1)  # 1 event with fake_prop="value_1" in the time range

            people_value_2 = self._get_actors(
                filters=filters, team=self.team, series=0, breakdown="value_2", includeRecordings=True
            )
            self.assertEqual(people_value_2[0][0]["distinct_ids"][0], "person2")
            self.assertEqual(people_value_2[0][2], 1)  # 1 event with fake_prop="value_2" in the time range

    @also_test_with_materialized_columns(person_properties=["name"])
    def test_breakdown_by_person_property_pie(self):
        self._create_multiple_people()

        with freeze_time("2020-01-04T13:01:01Z"):
            event_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdown": "name",
                        "breakdown_type": "person",
                        "display": "ActionsPie",
                        "events": [
                            {
                                "id": "watched movie",
                                "name": "watched movie",
                                "type": "events",
                                "order": 0,
                                "math": "dau",
                            }
                        ],
                    },
                ),
                self.team,
            )
            event_response = sorted(event_response, key=lambda resp: resp["breakdown_value"])
            self.assertLessEqual(
                {"breakdown_value": "person1", "aggregated_value": 1}.items(), event_response[0].items()
            )
            self.assertLessEqual(
                {"breakdown_value": "person2", "aggregated_value": 1}.items(), event_response[1].items()
            )
            self.assertLessEqual(
                {"breakdown_value": "person3", "aggregated_value": 1}.items(), event_response[2].items()
            )

        with freeze_time("2020-01-04T13:01:01Z"):
            event_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdowns": [{"type": "person", "property": "name"}],
                        "display": "ActionsPie",
                        "events": [
                            {
                                "id": "watched movie",
                                "name": "watched movie",
                                "type": "events",
                                "order": 0,
                                "math": "dau",
                            }
                        ],
                    },
                ),
                self.team,
            )
            event_response = sorted(event_response, key=lambda resp: resp["breakdown_value"])
            self.assertLessEqual(
                {"breakdown_value": ["person1"], "aggregated_value": 1}.items(), event_response[0].items()
            )
            self.assertLessEqual(
                {"breakdown_value": ["person2"], "aggregated_value": 1}.items(), event_response[1].items()
            )
            self.assertLessEqual(
                {"breakdown_value": ["person3"], "aggregated_value": 1}.items(), event_response[2].items()
            )

    @also_test_with_materialized_columns(person_properties=["name"])
    def test_breakdown_by_person_property_pie_with_event_dau_filter(self):
        self._create_multiple_people()

        filter = {
            "date_from": "-14d",
            "display": "ActionsPie",
            "events": [
                {
                    "id": "watched movie",
                    "name": "watched movie",
                    "type": "events",
                    "order": 0,
                    "math": "dau",
                    "properties": [
                        {
                            "key": "name",
                            "operator": "not_icontains",
                            "value": "person3",
                            "type": "person",
                        }
                    ],
                }
            ],
        }

        # single breakdown
        with freeze_time("2020-01-04T13:01:01Z"):
            event_response = self._run(
                Filter(
                    data={
                        **filter,
                        "breakdown": "name",
                        "breakdown_type": "person",
                    }
                ),
                self.team,
            )
            event_response = sorted(event_response, key=lambda resp: resp["breakdown_value"])
            self.assertEqual(len(event_response), 2)
            self.assertLessEqual(
                {"breakdown_value": "person1", "aggregated_value": 1}.items(), event_response[0].items()
            )
            self.assertLessEqual(
                {"breakdown_value": "person2", "aggregated_value": 1}.items(), event_response[1].items()
            )

        # multiple breakdowns
        with freeze_time("2020-01-04T13:01:01Z"):
            event_response = self._run(
                Filter(
                    data={
                        **filter,
                        "breakdowns": [
                            {
                                "type": "person",
                                "property": "name",
                            }
                        ],
                    }
                ),
                self.team,
            )
            event_response = sorted(event_response, key=lambda resp: resp["breakdown_value"])
            self.assertEqual(len(event_response), 2)
            self.assertLessEqual(
                {"breakdown_value": ["person1"], "aggregated_value": 1}.items(), event_response[0].items()
            )
            self.assertLessEqual(
                {"breakdown_value": ["person2"], "aggregated_value": 1}.items(), event_response[1].items()
            )

    @also_test_with_materialized_columns(person_properties=["name"])
    def test_filter_test_accounts_cohorts(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["person_1"], properties={"name": "John"})
        self._create_person(team_id=self.team.pk, distinct_ids=["person_2"], properties={"name": "Jane"})

        self._create_event(event="event_name", team=self.team, distinct_id="person_1")
        self._create_event(event="event_name", team=self.team, distinct_id="person_2")
        self._create_event(event="event_name", team=self.team, distinct_id="person_2")

        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "Jane", "type": "person"}]}],
        )
        self.team.test_account_filters = [{"key": "id", "value": cohort.pk, "type": "cohort"}]
        self.team.save()

        response = self._run(
            Filter(
                data={"events": [{"id": "event_name"}], "filter_test_accounts": True},
                team=self.team,
            ),
            self.team,
        )

        self.assertEqual(response[0]["count"], 2)
        self.assertEqual(response[0]["data"][-1], 2)

    def test_filter_by_precalculated_cohort(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["person_1"], properties={"name": "John"})
        self._create_person(team_id=self.team.pk, distinct_ids=["person_2"], properties={"name": "Jane"})

        self._create_event(event="event_name", team=self.team, distinct_id="person_1")
        self._create_event(event="event_name", team=self.team, distinct_id="person_2")
        self._create_event(event="event_name", team=self.team, distinct_id="person_2")

        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "Jane", "type": "person"}]}],
        )
        cohort.calculate_people_ch(pending_version=0)
        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "events": [{"id": "event_name"}],
                        "properties": [{"type": "cohort", "key": "id", "value": cohort.pk}],
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["count"], 2)
        self.assertEqual(response[0]["data"][-1], 2)

    @also_test_with_person_on_events_v2
    def test_breakdown_filter_by_precalculated_cohort(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["person_1"], properties={"name": "John"})
        self._create_person(team_id=self.team.pk, distinct_ids=["person_2"], properties={"name": "Jane"})

        self._create_event(event="event_name", team=self.team, distinct_id="person_1")
        self._create_event(event="event_name", team=self.team, distinct_id="person_2")
        self._create_event(event="event_name", team=self.team, distinct_id="person_2")

        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "Jane", "type": "person"}]}],
        )
        cohort.calculate_people_ch(pending_version=0)

        # single breakdown
        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "events": [{"id": "event_name"}],
                        "properties": [{"type": "cohort", "key": "id", "value": cohort.pk}],
                        "breakdown": "name",
                        "breakdown_type": "person",
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["breakdown_value"], "Jane")
        self.assertEqual(response[0]["count"], 2)
        self.assertEqual(response[0]["data"][-1], 2)

        # multiple breakdowns
        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "events": [{"id": "event_name"}],
                        "properties": [{"type": "cohort", "key": "id", "value": cohort.pk}],
                        "breakdowns": [
                            {
                                "type": "person",
                                "property": "name",
                            },
                        ],
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["breakdown_value"], ["Jane"])
        self.assertEqual(response[0]["count"], 2)
        self.assertEqual(response[0]["data"][-1], 2)

    def test_bar_chart_by_value(self):
        self._create_events()

        with freeze_time("2020-01-04T13:00:01Z"):
            # with self.assertNumQueries(16):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-7d",
                        "events": [{"id": "sign up"}, {"id": "no events"}],
                        "display": TRENDS_BAR_VALUE,
                    },
                ),
                self.team,
            )
        self.assertEqual(response[0]["aggregated_value"], 4)
        self.assertEqual(response[1]["aggregated_value"], 1)

    @snapshot_clickhouse_queries
    def test_trends_aggregate_by_distinct_id(self):
        # Stopgap until https://github.com/PostHog/meta/pull/39 is implemented

        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        self._create_person(team_id=self.team.pk, distinct_ids=["third"])

        with freeze_time("2019-12-24 03:45:34"):
            self._create_event(team=self.team, event="sign up", distinct_id="blabla")
            self._create_event(
                team=self.team, event="sign up", distinct_id="blabla"
            )  # aggregated by distinctID, so this should be ignored
            self._create_event(team=self.team, event="sign up", distinct_id="anonymous_id")
            self._create_event(team=self.team, event="sign up", distinct_id="third")

        with override_instance_config("AGGREGATE_BY_DISTINCT_IDS_TEAMS", f"{self.team.pk},4"):
            with freeze_time("2019-12-31T13:00:01Z"):
                daily_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            "interval": "day",
                            "events": [{"id": "sign up", "math": "dau"}],
                        },
                    ),
                    self.team,
                )

            self.assertEqual(daily_response[0]["data"][0], 3)

            with freeze_time("2019-12-31T13:00:01Z"):
                daily_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            "interval": "day",
                            "events": [{"id": "sign up", "math": "dau"}],
                            "properties": [
                                {
                                    "key": "$some_prop",
                                    "value": "some_val",
                                    "type": "person",
                                }
                            ],
                        },
                    ),
                    self.team,
                )
            self.assertEqual(daily_response[0]["data"][0], 2)

            # single breakdown person props
            with freeze_time("2019-12-31T13:00:01Z"):
                daily_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            "interval": "day",
                            "events": [{"id": "sign up", "math": "dau"}],
                            "breakdown_type": "person",
                            "breakdown": "$some_prop",
                        },
                    ),
                    self.team,
                )
            self.assertEqual(daily_response[0]["data"][0], 2)
            self.assertEqual(daily_response[0]["label"], "some_val")
            self.assertEqual(daily_response[1]["data"][0], 1)
            self.assertEqual(daily_response[1]["label"], "$$_posthog_breakdown_null_$$")

            # multiple breakdown person props
            with freeze_time("2019-12-31T13:00:01Z"):
                daily_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            "interval": "day",
                            "events": [{"id": "sign up", "math": "dau"}],
                            "breakdowns": [{"type": "person", "property": "$some_prop"}],
                        },
                    ),
                    self.team,
                )
            self.assertEqual(daily_response[0]["data"][0], 2)
            self.assertEqual(daily_response[0]["label"], "some_val")
            self.assertEqual(daily_response[1]["data"][0], 1)
            self.assertEqual(daily_response[1]["label"], "$$_posthog_breakdown_null_$$")

            # MAU
            with freeze_time("2019-12-31T13:00:03Z"):
                monthly_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            "interval": "day",
                            "events": [{"id": "sign up", "math": "monthly_active"}],
                        },
                    ),
                    self.team,
                )
            self.assertEqual(monthly_response[0]["data"][0], 3)  # this would be 2 without the aggregate hack

            with freeze_time("2019-12-31T13:00:01Z"):
                weekly_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            "interval": "day",
                            "events": [{"id": "sign up", "math": "weekly_active"}],
                        },
                    ),
                    self.team,
                )
            self.assertEqual(weekly_response[0]["data"][0], 3)  # this would be 2 without the aggregate hack

            # Make sure breakdown doesn't cause us to join on pdi
            PropertyDefinition.objects.create(
                team=self.team,
                name="$some_prop",
                property_type="String",
                type=PropertyDefinition.Type.EVENT,
            )
            with freeze_time("2019-12-31T13:00:01Z"):
                daily_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            "interval": "day",
                            "events": [{"id": "sign up", "math": "dau"}],
                            "breakdown": "$some_prop",
                        },
                    ),
                    self.team,
                )

    @also_test_with_materialized_columns(["$some_property"])
    def test_breakdown_filtering_limit(self):
        self._create_breakdown_events()
        with freeze_time("2020-01-04T13:01:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdown": "$some_property",
                        "events": [
                            {
                                "id": "sign up",
                                "name": "sign up",
                                "type": "events",
                                "order": 0,
                            }
                        ],
                    },
                ),
                self.team,
            )
            self.assertEqual(len(response), 25)
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "breakdowns": [{"property": "$some_property"}],
                        "events": [
                            {
                                "id": "sign up",
                                "name": "sign up",
                                "type": "events",
                                "order": 0,
                            }
                        ],
                    },
                ),
                self.team,
            )
            self.assertEqual(len(response), 25)

    @also_test_with_materialized_columns(event_properties=["order"], person_properties=["name"])
    def test_breakdown_with_person_property_filter(self):
        self._create_multiple_people()
        action = _create_action(name="watched movie", team=self.team)

        action_filter = {
            "date_from": "-14d",
            "actions": [{"id": action.pk, "type": "actions", "order": 0}],
            "properties": [{"key": "name", "value": "person2", "type": "person"}],
        }
        event_filter = {
            "date_from": "-14d",
            "events": [
                {
                    "id": "watched movie",
                    "name": "watched movie",
                    "type": "events",
                    "order": 0,
                    "properties": [
                        {
                            "key": "name",
                            "value": "person2",
                            "type": "person",
                        }
                    ],
                }
            ],
        }

        # single breakdown
        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        **action_filter,
                        "breakdown": "order",
                    },
                ),
                self.team,
            )
            event_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        **event_filter,
                        "breakdown": "order",
                    },
                ),
                self.team,
            )

        self.assertLessEqual({"count": 2, "breakdown_value": "2"}.items(), event_response[0].items())
        self.assertLessEqual({"count": 1, "breakdown_value": "1"}.items(), event_response[1].items())
        self.assertEntityResponseEqual(event_response, action_response)

        # multiple
        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        **action_filter,
                        "breakdowns": [{"property": "order"}],
                    },
                ),
                self.team,
            )
            event_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        **event_filter,
                        "breakdowns": [{"property": "order"}],
                    },
                ),
                self.team,
            )

        self.assertLessEqual({"count": 2, "breakdown_value": ["2"]}.items(), event_response[0].items())
        self.assertLessEqual({"count": 1, "breakdown_value": ["1"]}.items(), event_response[1].items())
        self.assertEntityResponseEqual(event_response, action_response)

    @also_test_with_materialized_columns(["$some_property"])
    def test_breakdown_filtering(self):
        self._create_events()
        filter = {
            "date_from": "-14d",
            "events": [
                {
                    "id": "sign up",
                    "name": "sign up",
                    "type": "events",
                    "order": 0,
                },
                {"id": "no events"},
            ],
        }
        # test breakdown filtering
        # single breakdown
        with freeze_time("2020-01-04T13:01:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        **filter,
                        "breakdown": "$some_property",
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["label"], "sign up - value")
        self.assertEqual(response[1]["label"], "sign up - other_value")
        self.assertEqual(response[2]["label"], "sign up - $$_posthog_breakdown_null_$$")
        self.assertEqual(response[3]["label"], "no events - $$_posthog_breakdown_null_$$")

        self.assertEqual(sum(response[0]["data"]), 2)
        self.assertEqual(sum(response[1]["data"]), 1)
        self.assertEqual(sum(response[2]["data"]), 2)
        self.assertEqual(sum(response[3]["data"]), 1)

        # test breakdown filtering
        with freeze_time("2020-01-04T13:01:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        **filter,
                        "breakdowns": [{"property": "$some_property"}],
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["label"], "sign up - value")
        self.assertEqual(response[1]["label"], "sign up - other_value")
        self.assertEqual(response[2]["label"], "sign up - $$_posthog_breakdown_null_$$")
        self.assertEqual(response[3]["label"], "no events - $$_posthog_breakdown_null_$$")

        self.assertEqual(sum(response[0]["data"]), 2)
        self.assertEqual(sum(response[1]["data"]), 1)
        self.assertEqual(sum(response[2]["data"]), 2)
        self.assertEqual(sum(response[3]["data"]), 1)

    def test_multiple_breakdowns_label_formatting(self):
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        with freeze_time("2020-01-01 00:06:34"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Chrome", "$variant": "1"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Chrome", "$variant": "2"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari", "$variant": "1"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari", "$variant": "1"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari", "$variant": "2"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari", "$variant": ""},
            )

        with freeze_time("2020-01-02 00:06:34"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari", "$variant": "2"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Safari", "$variant": "2"},
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value", "$browser": "Chrome", "$variant": ""},
            )

        filter = {
            "date_from": "-14d",
            "events": [
                {
                    "id": "sign up",
                    "name": "sign up",
                    "type": "events",
                    "order": 0,
                },
                {"id": "no events"},
            ],
        }

        with freeze_time("2020-01-04T13:00:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        **filter,
                        "breakdowns": [{"property": "$browser"}, {"property": "$variant"}],
                    },
                ),
                self.team,
            )

        self.assertEqual(len(response), 6)
        self.assertEqual(response[0]["label"], "sign up - Safari::2")
        self.assertEqual(response[1]["label"], "sign up - Safari::1")
        self.assertEqual(response[2]["label"], "sign up - Chrome::1")
        self.assertEqual(response[3]["label"], "sign up - Chrome::2")
        self.assertEqual(response[4]["label"], "sign up - Chrome::$$_posthog_breakdown_null_$$")
        self.assertEqual(response[5]["label"], "sign up - Safari::$$_posthog_breakdown_null_$$")

        # should group to "other" breakdowns
        with freeze_time("2020-01-04T13:00:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        **filter,
                        "breakdowns": [{"property": "$browser"}, {"property": "$variant"}],
                        "breakdown_limit": 1,
                    },
                ),
                self.team,
            )
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0]["label"], "sign up - Safari::2")
        self.assertEqual(response[1]["label"], "sign up - $$_posthog_breakdown_other_$$::$$_posthog_breakdown_other_$$")

    @also_test_with_materialized_columns(person_properties=["email"])
    def test_breakdown_filtering_persons(self):
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"email": "test@posthog.com"},
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"email": "test@gmail.com"},
        )
        self._create_person(team_id=self.team.pk, distinct_ids=["person3"], properties={})

        self._create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "val"},
        )
        self._create_event(
            event="sign up",
            distinct_id="person2",
            team=self.team,
            properties={"key": "val"},
        )
        self._create_event(
            event="sign up",
            distinct_id="person3",
            team=self.team,
            properties={"key": "val"},
        )

        filters: list[dict[str, Any]] = [
            {"breakdown": "email", "breakdown_type": "person"},
            {"breakdowns": [{"type": "person", "property": "email"}]},
        ]
        for breakdown_filter in filters:
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        **breakdown_filter,
                        "date_from": "-14d",
                        "events": [
                            {
                                "id": "sign up",
                                "name": "sign up",
                                "type": "events",
                                "order": 0,
                            }
                        ],
                    },
                ),
                self.team,
            )
            self.assertEqual(response[0]["label"], "test@gmail.com")
            self.assertEqual(response[1]["label"], "test@posthog.com")
            self.assertEqual(response[2]["label"], "$$_posthog_breakdown_null_$$")

            self.assertEqual(response[0]["count"], 1)
            self.assertEqual(response[1]["count"], 1)
            self.assertEqual(response[2]["count"], 1)

    # ensure that column names are properly handled when subqueries and person subquery share properties column
    @also_test_with_materialized_columns(event_properties=["key"], person_properties=["email"])
    def test_breakdown_filtering_persons_with_action_props(self):
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"email": "test@posthog.com"},
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"email": "test@gmail.com"},
        )
        self._create_person(team_id=self.team.pk, distinct_ids=["person3"], properties={})

        self._create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "val"},
        )
        self._create_event(
            event="sign up",
            distinct_id="person2",
            team=self.team,
            properties={"key": "val"},
        )
        self._create_event(
            event="sign up",
            distinct_id="person3",
            team=self.team,
            properties={"key": "val"},
        )
        action = _create_action(
            name="sign up",
            team=self.team,
            properties=[{"key": "key", "type": "event", "value": ["val"], "operator": "exact"}],
        )

        filters: list[dict[str, Any]] = [
            {"breakdown": "email", "breakdown_type": "person"},
            {"breakdowns": [{"property": "email", "type": "person"}]},
        ]
        for breakdown_filter in filters:
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        **breakdown_filter,
                        "date_from": "-14d",
                        "actions": [{"id": action.pk, "type": "actions", "order": 0}],
                    },
                ),
                self.team,
            )
            self.assertEqual(response[0]["label"], "test@gmail.com")
            self.assertEqual(response[1]["label"], "test@posthog.com")
            self.assertEqual(response[2]["label"], "$$_posthog_breakdown_null_$$")

            self.assertEqual(response[0]["count"], 1)
            self.assertEqual(response[1]["count"], 1)
            self.assertEqual(response[2]["count"], 1)

    @also_test_with_materialized_columns(["$current_url", "$os", "$browser"])
    def test_breakdown_filtering_with_properties(self):
        with freeze_time("2020-01-03T13:01:01Z"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={
                    "$current_url": "first url",
                    "$browser": "Firefox",
                    "$os": "Mac",
                },
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={
                    "$current_url": "first url",
                    "$browser": "Chrome",
                    "$os": "Windows",
                },
            )
        with freeze_time("2020-01-04T13:01:01Z"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={
                    "$current_url": "second url",
                    "$browser": "Firefox",
                    "$os": "Mac",
                },
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={
                    "$current_url": "second url",
                    "$browser": "Chrome",
                    "$os": "Windows",
                },
            )

        filters: list[dict[str, Any]] = [{"breakdown": "$current_url"}, {"breakdowns": [{"property": "$current_url"}]}]
        for breakdown_filter in filters:
            with freeze_time("2020-01-05T13:01:01Z"):
                response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "date_from": "-7d",
                            "events": [
                                {
                                    "id": "sign up",
                                    "name": "sign up",
                                    "type": "events",
                                    "order": 0,
                                    "properties": [{"key": "$os", "value": "Mac"}],
                                }
                            ],
                            "properties": [{"key": "$browser", "value": "Firefox"}],
                        },
                    ),
                    self.team,
                )

            response = sorted(response, key=lambda x: x["label"])
            self.assertEqual(response[0]["label"], "first url")
            self.assertEqual(response[1]["label"], "second url")

            self.assertEqual(sum(response[0]["data"]), 1)
            if "breakdown" in breakdown_filter:
                self.assertEqual(response[0]["breakdown_value"], "first url")
            else:
                self.assertEqual(response[0]["breakdown_value"], ["first url"])

            self.assertEqual(sum(response[1]["data"]), 1)
            if "breakdown" in breakdown_filter:
                self.assertEqual(response[1]["breakdown_value"], "second url")
            else:
                self.assertEqual(response[1]["breakdown_value"], ["second url"])

    @snapshot_clickhouse_queries
    def test_breakdown_filtering_with_properties_in_new_format(self):
        with freeze_time("2020-01-03T13:01:01Z"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={
                    "$current_url": "first url",
                    "$browser": "Firefox",
                    "$os": "Windows",
                },
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={
                    "$current_url": "first url",
                    "$browser": "Chrome",
                    "$os": "Mac",
                },
            )
        with freeze_time("2020-01-04T13:01:01Z"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla1",
                properties={
                    "$current_url": "second url",
                    "$browser": "Firefox",
                    "$os": "Mac",
                },
            )
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla2",
                properties={
                    "$current_url": "second url",
                    "$browser": "Chrome",
                    "$os": "Windows",
                },
            )

        filters: list[dict[str, Any]] = [
            {"breakdown": "$current_url"},
            {"breakdowns": [{"property": "$current_url"}]},
        ]
        for breakdown_filter in filters:
            with freeze_time("2020-01-05T13:01:01Z"):
                response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "date_from": "-14d",
                            "events": [
                                {
                                    "id": "sign up",
                                    "name": "sign up",
                                    "type": "events",
                                    "order": 0,
                                    "properties": [{"key": "$os", "value": "Mac"}],
                                }
                            ],
                            "properties": {
                                "type": "OR",
                                "values": [
                                    {"key": "$browser", "value": "Firefox"},
                                    {"key": "$os", "value": "Windows"},
                                ],
                            },
                        },
                    ),
                    self.team,
                )

            response = sorted(response, key=lambda x: x["label"])
            self.assertEqual(response[0]["label"], "second url")

            self.assertEqual(sum(response[0]["data"]), 1)
            if "breakdown" in breakdown_filter:
                self.assertEqual(response[0]["breakdown_value"], "second url")
            else:
                self.assertEqual(response[0]["breakdown_value"], ["second url"])

            # AND filter properties with disjoint set means results should be empty
            with freeze_time("2020-01-05T13:01:01Z"):
                response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "date_from": "-14d",
                            "events": [
                                {
                                    "id": "sign up",
                                    "name": "sign up",
                                    "type": "events",
                                    "order": 0,
                                    "properties": [{"key": "$os", "value": "Mac"}],
                                }
                            ],
                            "properties": {
                                "type": "AND",
                                "values": [
                                    {"key": "$browser", "value": "Firefox"},
                                    {"key": "$os", "value": "Windows"},
                                ],
                            },
                        },
                    ),
                    self.team,
                )

            response = sorted(response, key=lambda x: x["label"])
            self.assertEqual(len(response), 0)

    @also_test_with_person_on_events_v2
    @snapshot_clickhouse_queries
    def test_mau_with_breakdown_filtering_and_prop_filter(self):
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val", "filter_prop": "filter_val"},
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla2"],
            properties={"$some_prop": "some_val3", "filter_prop": "filter_val2"},
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla3"],
            properties={"$some_prop": "some_val2", "filter_prop": "filter_val"},
        )
        with freeze_time("2020-01-02T13:01:01Z"):
            self._create_event(team=self.team, event="sign up", distinct_id="blabla")
            self._create_event(team=self.team, event="sign up", distinct_id="blabla2")
            self._create_event(team=self.team, event="sign up", distinct_id="blabla3")
        with freeze_time("2020-01-03T13:01:01Z"):
            self._create_event(team=self.team, event="sign up", distinct_id="blabla")
            self._create_event(team=self.team, event="sign up", distinct_id="blabla2")
            self._create_event(team=self.team, event="sign up", distinct_id="blabla3")

        filters: list[dict[str, Any]] = [
            {"breakdown": "$some_prop", "breakdown_type": "person"},
            {"breakdowns": [{"property": "$some_prop", "type": "person"}]},
        ]
        for breakdown_filter in filters:
            with freeze_time("2020-01-04T13:01:01Z"):
                event_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "events": [{"id": "sign up", "math": "monthly_active"}],
                            "properties": [
                                {
                                    "key": "filter_prop",
                                    "value": "filter_val",
                                    "type": "person",
                                }
                            ],
                            "display": "ActionsLineGraph",
                        },
                    ),
                    self.team,
                )

            self.assertEqual(event_response[0]["label"], "some_val")
            self.assertEqual(event_response[1]["label"], "some_val2")

            self.assertEqual(sum(event_response[0]["data"]), 3)
            self.assertEqual(event_response[0]["data"][5], 1)

            self.assertEqual(sum(event_response[1]["data"]), 3)
            self.assertEqual(event_response[1]["data"][5], 1)

    @also_test_with_materialized_columns(["$some_property"])
    def test_dau_with_breakdown_filtering(self):
        sign_up_action, _ = self._create_events()
        with freeze_time("2020-01-02T13:01:01Z"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "other_value"},
            )

        filters: list[dict[str, Any]] = [
            {"breakdown": "$some_property"},
            {"breakdowns": [{"property": "$some_property"}]},
        ]
        for breakdown_filter in filters:
            with freeze_time("2020-01-04T13:01:01Z"):
                action_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "actions": [{"id": sign_up_action.id, "math": "dau"}],
                        },
                    ),
                    self.team,
                )
                event_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "events": [{"id": "sign up", "math": "dau"}],
                        },
                    ),
                    self.team,
                )

            self.assertEqual(event_response[0]["label"], "other_value", breakdown_filter)
            self.assertEqual(event_response[1]["label"], "value", breakdown_filter)
            self.assertEqual(event_response[2]["label"], "$$_posthog_breakdown_null_$$", breakdown_filter)

            self.assertEqual(sum(event_response[0]["data"]), 1, breakdown_filter)
            self.assertEqual(event_response[0]["data"][5], 1, breakdown_filter)

            self.assertEqual(sum(event_response[1]["data"]), 1, breakdown_filter)
            self.assertEqual(event_response[1]["data"][4], 1, breakdown_filter)  # property not defined

            self.assertEntityResponseEqual(action_response, event_response, breakdown_filter)

    @snapshot_clickhouse_queries
    def test_dau_with_breakdown_filtering_with_sampling(self):
        sign_up_action, _ = self._create_events()
        with freeze_time("2020-01-02T13:01:01Z"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "other_value"},
            )

        filters: list[dict[str, Any]] = [
            {"breakdown": "$some_property"},
            {"breakdowns": [{"property": "$some_property"}]},
        ]
        for breakdown_filter in filters:
            with freeze_time("2020-01-04T13:01:01Z"):
                action_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "sampling_factor": 1,
                            "actions": [{"id": sign_up_action.id, "math": "dau"}],
                        },
                    ),
                    self.team,
                )
                event_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "sampling_factor": 1,
                            "events": [{"id": "sign up", "math": "dau"}],
                        },
                    ),
                    self.team,
                )

            self.assertEqual(event_response[0]["label"], "other_value")
            self.assertEqual(event_response[1]["label"], "value")
            self.assertEqual(event_response[2]["label"], "$$_posthog_breakdown_null_$$")

            self.assertEqual(sum(event_response[0]["data"]), 1)
            self.assertEqual(event_response[0]["data"][5], 1)

            self.assertEqual(sum(event_response[1]["data"]), 1)
            self.assertEqual(event_response[1]["data"][4], 1)  # property not defined

            self.assertEntityResponseEqual(action_response, event_response)

    @also_test_with_materialized_columns(["$os", "$some_property"])
    def test_dau_with_breakdown_filtering_with_prop_filter(self):
        sign_up_action, _ = self._create_events()
        with freeze_time("2020-01-02T13:01:01Z"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "other_value", "$os": "Windows"},
            )

        filters: list[dict[str, Any]] = [
            {"breakdown": "$some_property"},
            {"breakdowns": [{"property": "$some_property"}]},
        ]
        for breakdown_filter in filters:
            with freeze_time("2020-01-04T13:01:01Z"):
                action_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "actions": [{"id": sign_up_action.id, "math": "dau"}],
                            "properties": [{"key": "$os", "value": "Windows"}],
                        },
                    ),
                    self.team,
                )
                event_response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "events": [{"id": "sign up", "math": "dau"}],
                            "properties": [{"key": "$os", "value": "Windows"}],
                        },
                    ),
                    self.team,
                )

            self.assertEqual(event_response[0]["label"], "other_value")

            self.assertEqual(sum(event_response[0]["data"]), 1)
            self.assertEqual(event_response[0]["data"][5], 1)  # property not defined

            self.assertEntityResponseEqual(action_response, event_response)

    @also_test_with_materialized_columns(event_properties=["$host"], person_properties=["$some_prop"])
    def test_against_clashing_entity_and_property_filter_naming(self):
        # Regression test for https://github.com/PostHog/posthog/issues/5814
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="blabla",
            properties={"$host": "app.example.com"},
            timestamp="2020-01-03T12:00:00Z",
        )

        filters: list[dict[str, Any]] = [
            {"breakdown": "$some_prop", "breakdown_type": "person"},
            {"breakdowns": [{"property": "$some_prop", "type": "person"}]},
        ]
        for breakdown_filter in filters:
            with freeze_time("2020-01-04T13:01:01Z"):
                response = self._run(
                    Filter(
                        team=self.team,
                        data={
                            **breakdown_filter,
                            "events": [
                                {
                                    "id": "$pageview",
                                    "properties": [
                                        {
                                            "key": "$host",
                                            "operator": "icontains",
                                            "value": ".com",
                                        }
                                    ],
                                }
                            ],
                            "properties": [
                                {
                                    "key": "$host",
                                    "value": ["app.example.com", "another.com"],
                                }
                            ],
                        },
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["count"], 1)

    # this ensures that the properties don't conflict when formatting params
    @also_test_with_materialized_columns(["$current_url"])
    def test_action_with_prop(self):
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )
        sign_up_action = Action.objects.create(
            team=self.team,
            name="sign up",
            steps_json=[
                {
                    "event": "sign up",
                    "properties": [
                        {
                            "key": "$current_url",
                            "type": "event",
                            "value": ["https://posthog.com/feedback/1234"],
                            "operator": "exact",
                        }
                    ],
                }
            ],
        )

        with freeze_time("2020-01-02T13:01:01Z"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$current_url": "https://posthog.com/feedback/1234"},
            )

        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "actions": [{"id": sign_up_action.id, "math": "dau"}],
                        "properties": [{"key": "$current_url", "value": "fake"}],
                    },
                ),
                self.team,
            )

        # if the params were shared it would be 1 because action would take precedence
        self.assertEqual(action_response[0]["count"], 0)

    @also_test_with_materialized_columns(["$current_url"], verify_no_jsonextract=False)
    def test_combine_all_cohort_and_icontains(self):
        # This caused some issues with SQL parsing
        sign_up_action, _ = self._create_events()
        cohort = Cohort.objects.create(
            team=self.team,
            name="a",
            groups=[{"properties": [{"key": "key", "value": "value", "type": "person"}]}],
        )
        action_response = self._run(
            Filter(
                team=self.team,
                data={
                    "actions": [{"id": sign_up_action.id, "math": "dau"}],
                    "properties": [{"key": "$current_url", "value": "ii", "operator": "icontains"}],
                    "breakdown": [cohort.pk, "all"],
                    "breakdown_type": "cohort",
                },
            ),
            self.team,
        )
        self.assertEqual(len(action_response), 0)

    @also_test_with_person_on_events_v2
    @snapshot_clickhouse_queries
    def test_person_filtering_in_cohort_in_action(self):
        # This caused some issues with SQL parsing
        sign_up_action, _ = self._create_events()
        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team,
            name="a",
            groups=[{"properties": [{"key": "$some_prop", "value": "some_val", "type": "person"}]}],
        )

        step = sign_up_action.steps[0]
        step.properties = [{"key": "id", "value": cohort.pk, "type": "cohort"}]

        sign_up_action.steps = [dataclasses.asdict(step)]
        sign_up_action.save()

        cohort.calculate_people_ch(pending_version=0)

        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "actions": [{"id": sign_up_action.id}],
                        "breakdown": "$some_property",
                    },
                ),
                self.team,
            )
        self.assertEqual(action_response[0]["breakdown_value"], "other_value")
        self.assertEqual(action_response[0]["count"], 1)

    @also_test_with_materialized_columns(event_properties=["key"], person_properties=["email"])
    def test_breakdown_user_props_with_filter(self):
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"email": "test@posthog.com"},
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"email": "test@gmail.com"},
        )
        person = self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person3"],
            properties={"email": "test@gmail.com"},
        )
        create_person_distinct_id(self.team.pk, "person1", str(person.uuid))

        self._create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "val"},
        )
        self._create_event(
            event="sign up",
            distinct_id="person2",
            team=self.team,
            properties={"key": "val"},
        )

        flush_persons_and_events()

        response = self._run(
            Filter(
                team=self.team,
                data={
                    "date_from": "-14d",
                    "breakdown": "email",
                    "breakdown_type": "person",
                    "events": [
                        {
                            "id": "sign up",
                            "name": "sign up",
                            "type": "events",
                            "order": 0,
                        }
                    ],
                    "properties": [
                        {
                            "key": "email",
                            "value": "@posthog.com",
                            "operator": "not_icontains",
                            "type": "person",
                        },
                        {"key": "key", "value": "val"},
                    ],
                },
            ),
            self.team,
        )

        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]["breakdown_value"], "test@gmail.com")

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(event_properties=["key"], person_properties=["email", "$os", "$browser"])
    def test_trend_breakdown_user_props_with_filter_with_partial_property_pushdowns(self):
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={
                "email": "test@posthog.com",
                "$os": "ios",
                "$browser": "chrome",
            },
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"email": "test@gmail.com", "$os": "ios", "$browser": "safari"},
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person3"],
            properties={
                "email": "test2@posthog.com",
                "$os": "android",
                "$browser": "chrome",
            },
        )
        # a second person with same properties, just so snapshot passes on different CH versions (indeterminate sorting currently)
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person32"],
            properties={
                "email": "test2@posthog.com",
                "$os": "android",
                "$browser": "chrome",
            },
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person4"],
            properties={
                "email": "test3@posthog.com",
                "$os": "android",
                "$browser": "safari",
            },
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person5"],
            properties={
                "email": "test4@posthog.com",
                "$os": "android",
                "$browser": "safari",
            },
        )
        self._create_person(
            team_id=self.team.pk,
            distinct_ids=["person6"],
            properties={
                "email": "test5@posthog.com",
                "$os": "android",
                "$browser": "safari",
            },
        )

        journeys_for(
            team=self.team,
            create_people=False,
            events_by_person={
                "person1": [
                    {
                        "event": "sign up",
                        "properties": {"key": "val"},
                        "timestamp": datetime(2020, 5, 1, 0),
                    }
                ],
                "person2": [
                    {
                        "event": "sign up",
                        "properties": {"key": "val"},
                        "timestamp": datetime(2020, 5, 1, 0),
                    }
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "properties": {"key": "val"},
                        "timestamp": datetime(2020, 5, 1, 0),
                    }
                ],
                "person32": [
                    {
                        "event": "sign up",
                        "properties": {"key": "val"},
                        "timestamp": datetime(2020, 5, 1, 0),
                    }
                ],
                "person4": [
                    {
                        "event": "sign up",
                        "properties": {"key": "val"},
                        "timestamp": datetime(2020, 5, 1, 0),
                    }
                ],
                "person5": [
                    {
                        "event": "sign up",
                        "properties": {"key": "val"},
                        "timestamp": datetime(2020, 5, 1, 0),
                    }
                ],
                "person6": [
                    {
                        "event": "sign up",
                        "properties": {"key": "val"},
                        "timestamp": datetime(2020, 5, 1, 0),
                    }
                ],
            },
        )

        response = self._run(
            Filter(
                team=self.team,
                data={
                    "date_from": "2020-01-01 00:00:00",
                    "date_to": "2020-07-01 00:00:00",
                    "breakdown": "email",
                    "breakdown_type": "person",
                    "events": [
                        {
                            "id": "sign up",
                            "name": "sign up",
                            "type": "events",
                            "order": 0,
                        }
                    ],
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "OR",
                                "values": [
                                    {
                                        "key": "email",
                                        "value": "@posthog.com",
                                        "operator": "not_icontains",
                                        "type": "person",
                                    },
                                    {"key": "key", "value": "val"},
                                ],
                            },
                            {
                                "type": "OR",
                                "values": [
                                    {
                                        "key": "$os",
                                        "value": "android",
                                        "operator": "exact",
                                        "type": "person",
                                    },
                                    {
                                        "key": "$browser",
                                        "value": "safari",
                                        "operator": "exact",
                                        "type": "person",
                                    },
                                ],
                            },
                        ],
                    },
                },
            ),
            self.team,
        )
        response = sorted(response, key=lambda item: item["breakdown_value"])
        self.assertEqual(len(response), 5)
        # person1 shouldn't be selected because it doesn't match the filter
        self.assertEqual(response[0]["breakdown_value"], "test2@posthog.com")
        self.assertEqual(response[1]["breakdown_value"], "test3@posthog.com")
        self.assertEqual(response[2]["breakdown_value"], "test4@posthog.com")
        self.assertEqual(response[3]["breakdown_value"], "test5@posthog.com")
        self.assertEqual(response[4]["breakdown_value"], "test@gmail.com")

        # now have more strict filters with entity props
        response = self._run(
            Filter(
                team=self.team,
                data={
                    "date_from": "2020-01-01 00:00:00",
                    "date_to": "2020-07-01 00:00:00",
                    "breakdown": "email",
                    "breakdown_type": "person",
                    "events": [
                        {
                            "id": "sign up",
                            "name": "sign up",
                            "type": "events",
                            "order": 0,
                            "properties": {
                                "type": "AND",
                                "values": [
                                    {"key": "key", "value": "val"},
                                    {
                                        "key": "email",
                                        "value": "@posthog.com",
                                        "operator": "icontains",
                                        "type": "person",
                                    },
                                ],
                            },
                        }
                    ],
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "$os",
                                        "value": "android",
                                        "operator": "exact",
                                        "type": "person",
                                    },
                                    {
                                        "key": "$browser",
                                        "value": "chrome",
                                        "operator": "exact",
                                        "type": "person",
                                    },
                                ],
                            }
                        ],
                    },
                },
            ),
            self.team,
        )
        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]["breakdown_value"], "test2@posthog.com")

    def _create_active_users_events(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["p0"], properties={"name": "p1"})
        self._create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        self._create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})

        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p0",
            timestamp="2020-01-03T11:00:00Z",
            properties={"key": "val"},
        )
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p0",
            timestamp="2020-01-03T12:00:00Z",
            properties={"key": "val"},
        )

        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-09T12:00:00Z",
            properties={"key": "bor"},
        )
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-09T12:00:00Z",
            properties={"key": "val"},
        )

        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-10T12:00:00Z",
            properties={"key": "bor"},
        )

        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "bor"},
        )

        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p0",
            timestamp="2020-01-12T12:00:00Z",
            properties={"key": "val"},
        )

    @snapshot_clickhouse_queries
    def test_weekly_active_users_aggregated_range_wider_than_week(self):
        self._create_active_users_events()

        data = {
            "date_from": "2020-01-01",
            "date_to": "2020-01-18",
            "display": TRENDS_TABLE,
            "events": [
                {
                    "id": "$pageview",
                    "type": "events",
                    "order": 0,
                    "math": "weekly_active",
                }
            ],
        }

        filter = Filter(team=self.team, data=data)
        result = self._run(filter, self.team)
        # Only p0 was active on 2020-01-18 or in the preceding 6 days
        self.assertEqual(result[0]["aggregated_value"], 1)

    @snapshot_clickhouse_queries
    def test_weekly_active_users_aggregated_range_wider_than_week_with_sampling(self):
        self._create_active_users_events()

        data = {
            "sampling_factor": 1,
            "date_from": "2020-01-01",
            "date_to": "2020-01-18",
            "display": TRENDS_TABLE,
            "events": [
                {
                    "id": "$pageview",
                    "type": "events",
                    "order": 0,
                    "math": "weekly_active",
                }
            ],
        }

        filter = Filter(team=self.team, data=data)
        result = self._run(filter, self.team)
        # Only p0 was active on 2020-01-18 or in the preceding 6 days
        self.assertEqual(result[0]["aggregated_value"], 1)

    @snapshot_clickhouse_queries
    def test_weekly_active_users_aggregated_range_narrower_than_week(self):
        self._create_active_users_events()

        data = {
            "date_from": "2020-01-11",
            "date_to": "2020-01-12",
            "display": TRENDS_TABLE,
            "events": [
                {
                    "id": "$pageview",
                    "type": "events",
                    "order": 0,
                    "math": "weekly_active",
                }
            ],
        }

        filter = Filter(team=self.team, data=data)
        result = self._run(filter, self.team)
        # All were active on 2020-01-12 or in the preceding 6 days
        self.assertEqual(result[0]["aggregated_value"], 3)

    @also_test_with_different_timezones
    @snapshot_clickhouse_queries
    def test_weekly_active_users_daily(self):
        self._create_active_users_events()

        data = {
            "date_from": "2020-01-08",
            "date_to": "2020-01-19",
            "events": [
                {
                    "id": "$pageview",
                    "type": "events",
                    "order": 0,
                    "math": "weekly_active",
                }
            ],
        }

        filter = Filter(team=self.team, data=data)
        result = self._run(filter, self.team)
        self.assertEqual(
            result[0]["days"],
            [
                "2020-01-08",
                "2020-01-09",
                "2020-01-10",
                "2020-01-11",
                "2020-01-12",
                "2020-01-13",
                "2020-01-14",
                "2020-01-15",
                "2020-01-16",
                "2020-01-17",
                "2020-01-18",
                "2020-01-19",
            ],
        )
        self.assertEqual(
            result[0]["data"],
            [
                1.0,  # 2020-01-08 - p0 only
                3.0,  # 2020-01-09 - p0, p1, and p2
                2.0,  # 2020-01-10 - p1, and p2
                2.0,  # 2020-01-11 - p1 and p2
                3.0,  # 2020-01-12 - p0, p1, and p2
                3.0,  # 2020-01-13 - p0, p1, and p2
                3.0,  # 2020-01-14 - p0, p1, and p2
                3.0,  # 2020-01-15 - p0, p1, and p2
                3.0,  # 2020-01-16 - p0, p1, and p2
                3.0,  # 2020-01-17 - p0, p1, and p2
                1.0,  # 2020-01-18 - p0 only
                0.0,  # 2020-01-19 - nobody
            ],
        )

    @also_test_with_different_timezones
    @snapshot_clickhouse_queries
    def test_weekly_active_groups_daily(self):
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )
        self._create_event_count_per_actor_events()
        with freeze_time("2020-01-19"):
            self._create_event(
                team=self.team,
                event="viewed video",
                distinct_id="blabla",
                properties={"$group_0": "bouba"},
            )

        data = {
            "date_from": "2020-01-08",
            "date_to": "2020-01-19",
            "events": [
                {
                    "id": "viewed video",
                    "type": "events",
                    "order": 0,
                    "math": "weekly_active",
                    "math_group_type_index": 0,
                }
            ],
        }

        filter = Filter(team=self.team, data=data)
        result = self._run(filter, self.team)
        self.assertEqual(
            result[0]["days"],
            [
                "2020-01-08",
                "2020-01-09",
                "2020-01-10",
                "2020-01-11",
                "2020-01-12",
                "2020-01-13",
                "2020-01-14",
                "2020-01-15",
                "2020-01-16",
                "2020-01-17",
                "2020-01-18",
                "2020-01-19",
            ],
        )
        self.assertEqual(
            result[0]["data"],
            [
                2,
                2,
                2,
                2,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                1,
            ],
        )

    @also_test_with_different_timezones
    def test_weekly_active_users_daily_based_on_action(self):
        action = _create_action(name="$pageview", team=self.team)
        self._create_active_users_events()

        data = {
            "date_from": "2020-01-08",
            "date_to": "2020-01-19",
            "actions": [
                {
                    "id": action.id,
                    "type": "actions",
                    "order": 0,
                    "math": "weekly_active",
                }
            ],
        }

        filter = Filter(team=self.team, data=data)
        result = self._run(filter, self.team)
        self.assertEqual(
            result[0]["days"],
            [
                "2020-01-08",
                "2020-01-09",
                "2020-01-10",
                "2020-01-11",
                "2020-01-12",
                "2020-01-13",
                "2020-01-14",
                "2020-01-15",
                "2020-01-16",
                "2020-01-17",
                "2020-01-18",
                "2020-01-19",
            ],
        )
        # Same as test_weekly_active_users_daily
        self.assertEqual(
            result[0]["data"],
            [1.0, 3.0, 2.0, 2.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 1.0, 0.0],
        )

    @also_test_with_different_timezones
    @snapshot_clickhouse_queries
    def test_weekly_active_users_weekly(self):
        """Test weekly active users with a week interval.

        When using WEEKLY_ACTIVE math with an interval of WEEK or greater,
        we should treat it like a normal unique users calculation (DAU) rather than
        the sliding window calculation used for daily intervals.
        """
        self._create_active_users_events()

        data = {
            "date_from": "2019-12-29",
            "date_to": "2020-01-18",
            "interval": "week",
            "events": [
                {
                    "id": "$pageview",
                    "type": "events",
                    "order": 0,
                    "math": "weekly_active",
                }
            ],
        }

        filter = Filter(team=self.team, data=data)
        result = self._run(filter, self.team)
        self.assertEqual(result[0]["days"], ["2019-12-29", "2020-01-05", "2020-01-12"])
        self.assertEqual(result[0]["data"], [1, 2, 1])

    @snapshot_clickhouse_queries
    def test_weekly_active_users_hourly(self):
        self._create_active_users_events()

        data = {
            "date_from": "2020-01-09T06:00:00Z",
            "date_to": "2020-01-09T17:00:00Z",
            "interval": "hour",
            "events": [
                {
                    "id": "$pageview",
                    "type": "events",
                    "order": 0,
                    "math": "weekly_active",
                }
            ],
        }

        filter = Filter(team=self.team, data=data)
        result = self._run(filter, self.team)
        self.assertEqual(
            result[0]["days"],
            [
                "2020-01-09 06:00:00",
                "2020-01-09 07:00:00",
                "2020-01-09 08:00:00",
                "2020-01-09 09:00:00",
                "2020-01-09 10:00:00",
                "2020-01-09 11:00:00",
                "2020-01-09 12:00:00",
                "2020-01-09 13:00:00",
                "2020-01-09 14:00:00",
                "2020-01-09 15:00:00",
                "2020-01-09 16:00:00",
                "2020-01-09 17:00:00",
            ],
        )

        self.assertEqual(
            result[0]["data"],
            [1, 1, 1, 1, 1, 1, 3, 3, 3, 3, 3, 3],
        )

    def test_weekly_active_users_hourly_full_week(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["p0"])
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p0",
            timestamp="2020-01-03T10:59:59Z",
            properties={"key": "val"},
        )
        self._create_person(team_id=self.team.pk, distinct_ids=["p1"])
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-03T11:00:00Z",
            properties={"key": "val"},
        )
        self._create_person(team_id=self.team.pk, distinct_ids=["p2"])
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-03T11:00:01Z",
            properties={"key": "val"},
        )

        data = {
            "date_from": "2020-01-03T00:00:00Z",
            "date_to": "2020-01-11T17:00:00Z",
            "interval": "hour",
            "events": [
                {
                    "id": "$pageview",
                    "type": "events",
                    "order": 0,
                    "math": "weekly_active",
                }
            ],
        }

        filter = Filter(team=self.team, data=data)
        result = self._run(filter, self.team)
        self.assertEqual(24 * 7 * 3, sum(result[0]["data"]))
        self.assertEqual("2020-01-03 10:00:00", result[0]["days"][10])
        self.assertEqual(1, result[0]["data"][10])
        self.assertEqual("2020-01-03 11:00:00", result[0]["days"][11])
        self.assertTrue(all(x == 3 for x in result[0]["data"][11:178]))
        self.assertEqual(2, result[0]["data"][178])
        self.assertEqual("2020-01-10 10:00:00", result[0]["days"][178])

    def test_weekly_active_users_daily_based_on_action_with_zero_person_ids(self):
        # only a person-on-event test
        if not get_instance_setting("PERSON_ON_EVENTS_ENABLED"):
            return True

        action = _create_action(name="$pageview", team=self.team)
        self._create_active_users_events()

        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p5",
            timestamp="2020-01-03T12:00:00Z",
            properties={"key": "val"},
            person_id="00000000-0000-0000-0000-000000000000",
        )
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p6",
            timestamp="2020-01-03T12:00:00Z",
            properties={"key": "val"},
            person_id="00000000-0000-0000-0000-000000000000",
        )

        data = {
            "date_from": "2020-01-08",
            "date_to": "2020-01-19",
            "actions": [
                {
                    "id": action.id,
                    "type": "actions",
                    "order": 0,
                    "math": "weekly_active",
                }
            ],
        }

        filter = Filter(team=self.team, data=data)
        result = self._run(filter, self.team)
        # Zero person IDs shouldn't be counted
        self.assertEqual(
            result[0]["data"],
            [1.0, 3.0, 2.0, 2.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 1.0, 0.0],
        )

    @also_test_with_materialized_columns(["key"])
    def test_breakdown_weekly_active_users_daily(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-09T12:00:00Z",
            properties={"key": "val"},
        )
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-10T12:00:00Z",
            properties={"key": "val"},
        )
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

        self._create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-09T12:00:00Z",
            properties={"key": "val"},
        )
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

        data = {
            "date_from": "2020-01-01T00:00:00Z",
            "date_to": "2020-01-12T00:00:00Z",
            "breakdown": "key",
            "events": [
                {
                    "id": "$pageview",
                    "type": "events",
                    "order": 0,
                    "math": "weekly_active",
                }
            ],
        }

        filter = Filter(team=self.team, data=data)
        result = self._run(filter, self.team)
        self.assertEqual(
            result[0]["data"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 2.0, 2.0, 2.0],
        )

    @also_test_with_materialized_columns(person_properties=["name"])
    @snapshot_clickhouse_queries
    def test_weekly_active_users_filtering(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "person-1"})
        self._create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "person-2"})
        self._create_person(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "person-3"})

        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-09T12:00:00Z",
        )
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-10T12:00:00Z",
        )
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp="2020-01-11T12:00:00Z",
        )

        filter = Filter(
            team=self.team,
            data={
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "math": "weekly_active",
                    }
                ],
                "properties": [
                    {
                        "key": "name",
                        "operator": "exact",
                        "value": ["person-1", "person-2"],
                        "type": "person",
                    }
                ],
            },
        )

        result = self._run(filter, self.team)
        self.assertEqual(
            result[0]["data"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 2.0, 2.0, 2.0],
        )

    @snapshot_clickhouse_queries
    def test_breakdown_weekly_active_users_daily_based_on_action(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-09T12:00:00Z",
            properties={"key": "val"},
        )
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-10T12:00:00Z",
            properties={"key": "val"},
        )
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

        self._create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-09T12:00:00Z",
            properties={"key": "val"},
        )
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

        self._create_person(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "p3"})
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp="2020-01-09T12:00:00Z",
            properties={"key": "val"},
        )
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "name",
                            "operator": "exact",
                            "value": ["p1", "p2"],
                            "type": "person",
                        }
                    ]
                }
            ],
        )

        pageview_action = _create_action(
            name="$pageview",
            team=self.team,
            properties=[
                {
                    "key": "name",
                    "operator": "exact",
                    "value": ["p1", "p2", "p3"],
                    "type": "person",
                },
                {"type": "cohort", "key": "id", "value": cohort.pk},
            ],
        )

        cohort.calculate_people_ch(pending_version=0)

        data = {
            "date_from": "2020-01-01T00:00:00Z",
            "date_to": "2020-01-12T00:00:00Z",
            "breakdown": "key",
            "actions": [
                {
                    "id": pageview_action.id,
                    "type": "actions",
                    "order": 0,
                    "math": "weekly_active",
                }
            ],
        }

        filter = Filter(team=self.team, data=data)
        result = self._run(filter, self.team)
        self.assertEqual(
            result[0]["data"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 2.0, 2.0, 2.0],
        )

    @also_test_with_materialized_columns(["key"])
    @snapshot_clickhouse_queries
    def test_breakdown_weekly_active_users_aggregated(self):
        self._create_active_users_events()

        data = {
            "date_from": "2020-01-11",
            "date_to": "2020-01-11",
            "display": TRENDS_TABLE,
            "events": [
                {
                    "id": "$pageview",
                    "type": "events",
                    "order": 0,
                    "math": "weekly_active",
                }
            ],
            "breakdown": "key",
        }

        filter = Filter(team=self.team, data=data)
        result = self._run(filter, self.team)
        # All were active on 2020-01-12 or in the preceding 6 days
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["breakdown_value"], "bor")
        self.assertEqual(result[0]["aggregated_value"], 2)
        self.assertEqual(result[1]["breakdown_value"], "val")
        self.assertEqual(result[1]["aggregated_value"], 2)

    # TODO: test_account_filters conversion
    # @also_test_with_materialized_columns(event_properties=["key"], person_properties=["name"])
    # def test_filter_test_accounts(self):
    #     self._create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
    #     self._create_event(
    #         team=self.team,
    #         event="$pageview",
    #         distinct_id="p1",
    #         timestamp="2020-01-11T12:00:00Z",
    #         properties={"key": "val"},
    #     )

    #     self._create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
    #     self._create_event(
    #         team=self.team,
    #         event="$pageview",
    #         distinct_id="p2",
    #         timestamp="2020-01-11T12:00:00Z",
    #         properties={"key": "val"},
    #     )
    #     self.team.test_account_filters = [{"key": "name", "value": "p1", "operator": "is_not", "type": "person"}]
    #     self.team.save()
    #     filter = Filter(
    #         team=self.team,
    #         data={
    #             "date_from": "2020-01-01T00:00:00Z",
    #             "date_to": "2020-01-12T00:00:00Z",
    #             "events": [{"id": "$pageview", "type": "events", "order": 0}],
    #             "filter_test_accounts": True,
    #         },
    #     )
    #     result = self._run(filter, self.team)
    #     self.assertEqual(result[0]["count"], 1)
    #     filter2 = Filter(
    #         team=self.team,
    #         data={
    #             "date_from": "2020-01-01T00:00:00Z",
    #             "date_to": "2020-01-12T00:00:00Z",
    #             "events": [{"id": "$pageview", "type": "events", "order": 0}],
    #         },
    #     )
    #     result = self._run(filter2, self.team)
    #     self.assertEqual(result[0]["count"], 2)
    #     result = self._run(filter.shallow_clone({"breakdown": "key"}), self.team)
    #     self.assertEqual(result[0]["count"], 1)

    @also_test_with_materialized_columns(["$some_property"])
    def test_breakdown_filtering_bar_chart_by_value(self):
        self._create_events()

        # test breakdown filtering
        with freeze_time("2020-01-04T13:01:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-7d",
                        "breakdown": "$some_property",
                        "events": [
                            {
                                "id": "sign up",
                                "name": "sign up",
                                "type": "events",
                                "order": 0,
                            }
                        ],
                        "display": TRENDS_BAR_VALUE,
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["aggregated_value"], 1)
        self.assertEqual(response[1]["aggregated_value"], 1)
        self.assertEqual(response[2]["aggregated_value"], 2)  # the events without breakdown value
        self.assertEqual(response[0]["days"], [])

    @also_test_with_materialized_columns(person_properties=["key", "key_2"], verify_no_jsonextract=False)
    def test_breakdown_multiple_cohorts(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"key": "value"})
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )

        self._create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"key_2": "value_2"})
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )

        self._create_person(team_id=self.team.pk, distinct_ids=["p3"], properties={"key_2": "value_2"})
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )

        cohort1 = _create_cohort(
            team=self.team,
            name="cohort_1",
            groups=[{"properties": [{"key": "key", "value": "value", "type": "person"}]}],
        )
        cohort2 = _create_cohort(
            team=self.team,
            name="cohort_2",
            groups=[{"properties": [{"key": "key_2", "value": "value_2", "type": "person"}]}],
        )

        # try different versions
        cohort1.calculate_people_ch(pending_version=1)
        cohort2.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):  # Normally this is False in tests
            with freeze_time("2020-01-04T13:01:01Z"):
                res = self._run(
                    Filter(
                        team=self.team,
                        data={
                            "date_from": "-7d",
                            "events": [{"id": "$pageview"}],
                            "properties": [],
                            "breakdown": [cohort1.pk, cohort2.pk],
                            "breakdown_type": "cohort",
                        },
                    ),
                    self.team,
                )

        self.assertEqual(res[0]["count"], 2)
        self.assertEqual(res[1]["count"], 1)

    @also_test_with_materialized_columns(person_properties=["key", "key_2"], verify_no_jsonextract=False)
    def test_breakdown_single_cohort(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"key": "value"})
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )

        self._create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"key_2": "value_2"})
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )

        self._create_person(team_id=self.team.pk, distinct_ids=["p3"], properties={"key_2": "value_2"})
        self._create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )

        cohort1 = _create_cohort(
            team=self.team,
            name="cohort_1",
            groups=[{"properties": [{"key": "key", "value": "value", "type": "person"}]}],
        )

        cohort1.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):  # Normally this is False in tests
            with freeze_time("2020-01-04T13:01:01Z"):
                res = self._run(
                    Filter(
                        team=self.team,
                        data={
                            "date_from": "-7d",
                            "events": [{"id": "$pageview"}],
                            "properties": [],
                            "breakdown": cohort1.pk,
                            "breakdown_type": "cohort",
                        },
                    ),
                    self.team,
                )

        self.assertEqual(res[0]["count"], 1)

    @also_test_with_materialized_columns(["key", "$current_url"])
    def test_filtering_with_action_props(self):
        self._create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "val", "$current_url": "/some/page"},
        )
        self._create_event(
            event="sign up",
            distinct_id="person2",
            team=self.team,
            properties={"key": "val", "$current_url": "/some/page"},
        )
        self._create_event(
            event="sign up",
            distinct_id="person3",
            team=self.team,
            properties={"key": "val", "$current_url": "/another/page"},
        )

        action = Action.objects.create(
            name="sign up",
            team=self.team,
            steps_json=[
                {
                    "event": "sign up",
                    "url": "/some/page",
                    "properties": [{"key": "key", "type": "event", "value": ["val"], "operator": "exact"}],
                }
            ],
        )

        response = self._run(
            Filter(
                data={
                    "date_from": "-14d",
                    "actions": [{"id": action.pk, "type": "actions", "order": 0}],
                }
            ),
            self.team,
        )

        self.assertEqual(response[0]["count"], 2)

    @pytest.mark.skip(reason="We dont currently error out for this, but fallback instead. Good enough for now")
    def test_trends_math_without_math_property(self):
        with self.assertRaises(ValidationError):
            self._run(Filter(data={"events": [{"id": "sign up", "math": "sum"}]}), self.team)

    @patch("posthog.hogql_queries.insights.trends.trends_query_runner.execute_hogql_query")
    def test_should_throw_exception(self, patch_sync_execute):
        self._create_events()
        patch_sync_execute.side_effect = Exception()
        # test breakdown filtering
        with self.assertRaises(Exception):
            with self.settings(TEST=False, DEBUG=False):
                self._run(
                    Filter(
                        data={
                            "events": [
                                {
                                    "id": "sign up",
                                    "name": "sign up",
                                    "type": "events",
                                    "order": 0,
                                }
                            ]
                        }
                    ),
                    self.team,
                )

    @also_test_with_different_timezones
    @snapshot_clickhouse_queries
    def test_timezones_hourly_relative_from(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["blabla"], properties={})
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={
                "$current_url": "first url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-04T22:01:01",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={
                "$current_url": "first url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-05T07:01:01",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={
                "$current_url": "first url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-05T08:01:01",
        )

        query_time = datetime(2020, 1, 5, 10, 1, 1, tzinfo=ZoneInfo(self.team.timezone))

        with freeze_time(query_time):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "dStart",
                        "interval": "hour",
                        "events": [{"id": "sign up", "name": "sign up", "math": "dau"}],
                    },
                ),
                self.team,
            )
            self.assertEqual(
                response[0]["labels"],
                [
                    "5-Jan 00:00",
                    "5-Jan 01:00",
                    "5-Jan 02:00",
                    "5-Jan 03:00",
                    "5-Jan 04:00",
                    "5-Jan 05:00",
                    "5-Jan 06:00",
                    "5-Jan 07:00",
                    "5-Jan 08:00",
                    "5-Jan 09:00",
                    "5-Jan 10:00",
                ],
            )
            self.assertEqual(response[0]["data"], [0.0, 0.0, 0.0, 0.0, 0, 0, 0, 1, 1, 0, 0])

            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "dStart",
                        "interval": "hour",
                        "events": [{"id": "sign up", "name": "sign up"}],
                    },
                ),
                self.team,
            )

            self.assertEqual(
                response[0]["labels"],
                [
                    "5-Jan 00:00",
                    "5-Jan 01:00",
                    "5-Jan 02:00",
                    "5-Jan 03:00",
                    "5-Jan 04:00",
                    "5-Jan 05:00",
                    "5-Jan 06:00",
                    "5-Jan 07:00",
                    "5-Jan 08:00",
                    "5-Jan 09:00",
                    "5-Jan 10:00",
                ],
            )
            self.assertEqual(response[0]["data"], [0.0, 0.0, 0.0, 0.0, 0, 0, 0, 1, 1, 0, 0])

    @also_test_with_different_timezones
    def test_timezones_hourly_absolute_from(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["blabla"], properties={})
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={
                "$current_url": "first url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-02T17:01:01",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={
                "$current_url": "second url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-03T17:01:01",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={
                "$current_url": "second url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-06T00:30:01",  # Shouldn't be included anywhere
        )

        # Custom date range, single day, hourly interval
        response = self._run(
            Filter(
                data={
                    "date_from": "2020-01-03",
                    "date_to": "2020-01-03 23:59:59",
                    "interval": "hour",
                    "events": [{"id": "sign up", "name": "sign up"}],
                },
                team=self.team,
            ),
            self.team,
        )

        self.assertEqual(
            response[0]["days"],
            [
                "2020-01-03 00:00:00",
                "2020-01-03 01:00:00",
                "2020-01-03 02:00:00",
                "2020-01-03 03:00:00",
                "2020-01-03 04:00:00",
                "2020-01-03 05:00:00",
                "2020-01-03 06:00:00",
                "2020-01-03 07:00:00",
                "2020-01-03 08:00:00",
                "2020-01-03 09:00:00",
                "2020-01-03 10:00:00",
                "2020-01-03 11:00:00",
                "2020-01-03 12:00:00",
                "2020-01-03 13:00:00",
                "2020-01-03 14:00:00",
                "2020-01-03 15:00:00",
                "2020-01-03 16:00:00",
                "2020-01-03 17:00:00",
                "2020-01-03 18:00:00",
                "2020-01-03 19:00:00",
                "2020-01-03 20:00:00",
                "2020-01-03 21:00:00",
                "2020-01-03 22:00:00",
                "2020-01-03 23:00:00",
            ],
        )
        self.assertEqual(response[0]["data"][17], 1)
        self.assertEqual(len(response[0]["data"]), 24)

        # Custom date range, single day, dayly interval
        response = self._run(
            Filter(
                data={
                    "date_from": "2020-01-03",
                    "date_to": "2020-01-03",
                    "events": [{"id": "sign up", "name": "sign up"}],
                },
                team=self.team,
            ),
            self.team,
        )
        self.assertEqual(response[0]["data"], [1.0])

    @also_test_with_different_timezones
    @snapshot_clickhouse_queries
    def test_timezones_daily(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["blabla"], properties={})
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={
                "$current_url": "first url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-02T17:01:01",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={
                "$current_url": "second url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-03T17:01:01",
        )
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={
                "$current_url": "second url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-06T00:30:01",  # Shouldn't be included anywhere
        )

        with freeze_time(datetime(2020, 1, 5, 5, 0, tzinfo=ZoneInfo(self.team.timezone))):
            response = self._run(
                Filter(
                    data={
                        "date_from": "-7d",
                        "events": [{"id": "sign up", "name": "sign up"}],
                    },
                    team=self.team,
                ),
                self.team,
            )

        self.assertEqual(response[0]["data"], [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0])
        self.assertEqual(
            response[0]["labels"],
            [
                "29-Dec-2019",
                "30-Dec-2019",
                "31-Dec-2019",
                "1-Jan-2020",
                "2-Jan-2020",
                "3-Jan-2020",
                "4-Jan-2020",
                "5-Jan-2020",
            ],
        )

        # DAU
        with freeze_time("2020-01-05T13:01:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "events": [{"id": "sign up", "name": "sign up", "math": "dau"}],
                    },
                ),
                self.team,
            )
        self.assertEqual(
            response[0]["data"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0],
        )
        self.assertEqual(
            response[0]["labels"],
            [
                "22-Dec-2019",
                "23-Dec-2019",
                "24-Dec-2019",
                "25-Dec-2019",
                "26-Dec-2019",
                "27-Dec-2019",
                "28-Dec-2019",
                "29-Dec-2019",
                "30-Dec-2019",
                "31-Dec-2019",
                "1-Jan-2020",
                "2-Jan-2020",
                "3-Jan-2020",
                "4-Jan-2020",
                "5-Jan-2020",
            ],
        )

        with freeze_time("2020-01-05T13:01:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-7d",
                        "events": [
                            {
                                "id": "sign up",
                                "name": "sign up",
                                "math": "weekly_active",
                            }
                        ],
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["data"], [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
        self.assertEqual(
            response[0]["labels"],
            [
                "29-Dec-2019",
                "30-Dec-2019",
                "31-Dec-2019",
                "1-Jan-2020",
                "2-Jan-2020",
                "3-Jan-2020",
                "4-Jan-2020",
                "5-Jan-2020",
            ],
        )

        with freeze_time("2020-01-05T13:01:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-7d",
                        "events": [{"id": "sign up", "name": "sign up", "breakdown": "$os"}],
                    },
                ),
                self.team,
            )

        self.assertEqual(response[0]["data"], [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0])
        self.assertEqual(
            response[0]["labels"],
            [
                "29-Dec-2019",
                "30-Dec-2019",
                "31-Dec-2019",
                "1-Jan-2020",
                "2-Jan-2020",
                "3-Jan-2020",
                "4-Jan-2020",
                "5-Jan-2020",
            ],
        )

        #  breakdown + DAU
        with freeze_time("2020-01-05T13:01:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-7d",
                        "breakdown": "$os",
                        "events": [{"id": "sign up", "name": "sign up", "math": "dau"}],
                    },
                ),
                self.team,
            )
            self.assertEqual(response[0]["data"], [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0])

    # Regression test to ensure we handle non-deterministic timezones correctly
    # US/Pacific for example changes from PST to PDT due to Daylight Savings Time
    # In 2022, this happened on November 6, and previously we had a bug where
    # a graph starting before that date and ending after it would show all 0s
    # after November 6. Thus, this test ensures that doesn't happen
    @snapshot_clickhouse_queries
    def test_non_deterministic_timezones(self):
        self.team.timezone = "US/Pacific"
        self.team.save()
        self._create_person(team_id=self.team.pk, distinct_ids=["blabla"], properties={})

        with freeze_time("2022-11-03T01:01:01Z"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={
                    "$current_url": "first url",
                    "$browser": "Firefox",
                    "$os": "Mac",
                },
            )

        with freeze_time("2022-11-10T01:01:01Z"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={
                    "$current_url": "second url",
                    "$browser": "Firefox",
                    "$os": "Mac",
                },
            )

        with freeze_time("2022-11-17T08:30:01Z"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={
                    "$current_url": "second url",
                    "$browser": "Firefox",
                    "$os": "Mac",
                },
            )

        with freeze_time("2022-11-24T08:30:01Z"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={
                    "$current_url": "second url",
                    "$browser": "Firefox",
                    "$os": "Mac",
                },
            )

        with freeze_time("2022-11-30T08:30:01Z"):
            self._create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={
                    "$current_url": "second url",
                    "$browser": "Firefox",
                    "$os": "Mac",
                },
            )

        with freeze_time("2022-11-30T13:01:01Z"):
            response = self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-30d",
                        "events": [{"id": "sign up", "name": "sign up"}],
                        "interval": "week",
                    },
                ),
                self.team,
            )

        # The key is to not get any 0s here
        self.assertEqual(response[0]["data"], [1.0, 1.0, 1.0, 1.0, 1.0])

    @also_test_with_different_timezones
    @snapshot_clickhouse_queries
    def test_timezones_weekly(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["blabla"], properties={})
        self._create_event(  # This event is before the time range (but counts towards week of 2020-01-06 in Monday mode)
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={
                "$current_url": "first url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-11T19:01:01",  # Saturday; TRICKY: This is the next UTC day in America/Phoenix
        )
        self._create_event(  # This event should count towards week of 2020-01-12 (or 2020-01-06 in Monday mode)
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={
                "$current_url": "first url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-12T02:01:01",  # Sunday; TRICKY: This is the previous UTC day in Asia/Tokyo
        )
        self._create_event(  # This event should count towards week of 2020-01-19 (or 2020-01-20 in Monday mode)
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={
                "$current_url": "second url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-21T18:01:01",  # Tuesday; TRICKY: This is the next UTC day in America/Phoenix
        )

        self.team.week_start_day = 0  # DB value for WeekStartDay.SUNDAY (the default, but let's be explicit)
        self.team.save()

        # TRICKY: This is the previous UTC day in Asia/Tokyo
        with freeze_time(datetime(2020, 1, 26, 3, 0, tzinfo=ZoneInfo(self.team.timezone))):
            # Total volume query
            response_sunday = self._run(
                Filter(
                    data={
                        "date_from": "-14d",
                        "interval": "week",
                        "events": [{"id": "sign up", "name": "sign up"}],
                    },
                    team=self.team,
                ),
                self.team,
            )

        self.assertEqual(response_sunday[0]["days"], ["2020-01-12", "2020-01-19", "2020-01-26"])
        self.assertEqual(response_sunday[0]["data"], [1.0, 1.0, 0.0])

        self.team.week_start_day = 1  # DB value for WeekStartDay.MONDAY
        self.team.save()

        # TRICKY: This is the previous UTC day in Asia/Tokyo
        with freeze_time(datetime(2020, 1, 26, 3, 0, tzinfo=ZoneInfo(self.team.timezone))):
            # Total volume query
            response_monday = self._run(
                Filter(
                    data={
                        "date_from": "-14d",
                        "interval": "week",
                        "events": [{"id": "sign up", "name": "sign up"}],
                    },
                    team=self.team,
                ),
                self.team,
            )

        self.assertEqual(response_monday[0]["days"], ["2020-01-06", "2020-01-13", "2020-01-20"])
        self.assertEqual(response_monday[0]["data"], [1.0, 0.0, 1.0])  # only includes events after 2020-01-12

    def test_same_day(self):
        self._create_person(team_id=self.team.pk, distinct_ids=["blabla"], properties={})
        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="blabla",
            properties={
                "$current_url": "first url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-03T01:01:01Z",
        )
        response = self._run(
            Filter(
                team=self.team,
                data={
                    "date_from": "2020-01-03",
                    "date_to": "2020-01-03",
                    "events": [{"id": "sign up", "name": "sign up"}],
                },
            ),
            self.team,
        )
        self.assertEqual(response[0]["data"], [1.0])

    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=True)
    @snapshot_clickhouse_queries
    def test_same_day_with_person_on_events_v2(self):
        person_id1 = str(uuid.uuid4())
        person_id2 = str(uuid.uuid4())

        self._create_person(team_id=self.team.pk, distinct_ids=["distinctid1"], properties={})
        self._create_person(team_id=self.team.pk, distinct_ids=["distinctid2"], properties={})

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="distinctid1",
            properties={
                "$current_url": "first url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-03T01:01:01Z",
            person_id=person_id1,
        )

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="distinctid2",
            properties={
                "$current_url": "first url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-03T01:01:01Z",
            person_id=person_id2,
        )

        create_person_id_override_by_distinct_id("distinctid1", "distinctid2", self.team.pk)

        response = self._run(
            Filter(
                team=self.team,
                data={
                    "date_from": "2020-01-03",
                    "date_to": "2020-01-03",
                    "events": [{"id": "sign up", "name": "sign up"}],
                },
            ),
            self.team,
        )
        self.assertEqual(response[0]["data"], [2.0])

        response = self._run(
            Filter(
                team=self.team,
                data={
                    "date_from": "2020-01-03",
                    "date_to": "2020-01-03",
                    "events": [{"id": "sign up", "name": "sign up", "math": "dau"}],
                },
            ),
            self.team,
        )
        self.assertEqual(response[0]["data"], [1.0])

    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=True)
    @snapshot_clickhouse_queries
    def test_same_day_with_person_on_events_v2_latest_override(self):
        # In this test we check that we always prioritize the latest override (based on the `version`)
        # To do so, we first create an override to a person 2 that did not perform the event we're building
        # the insight on, which should lead us to have 2 DAUs. We then create an override to a person 3 that did
        # have the event, which should lead us to have 1 DAU only, since persons 1 and 3 are now the same person.
        # Lastly, we create an override back to person 2 and check that DAUs go back to 2.
        person_id1 = str(uuid.uuid4())
        person_id2 = str(uuid.uuid4())
        person_id3 = str(uuid.uuid4())

        self._create_person(team_id=self.team.pk, distinct_ids=["distinctid1"], properties={})
        self._create_person(team_id=self.team.pk, distinct_ids=["distinctid2"], properties={})
        self._create_person(team_id=self.team.pk, distinct_ids=["distinctid3"], properties={})

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="distinctid1",
            properties={
                "$current_url": "first url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-03T01:01:01Z",
            person_id=person_id1,
        )

        self._create_event(
            team=self.team,
            event="some other event",
            distinct_id="distinctid2",
            properties={
                "$current_url": "first url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-03T01:01:01Z",
            person_id=person_id2,
        )

        self._create_event(
            team=self.team,
            event="sign up",
            distinct_id="distinctid3",
            properties={
                "$current_url": "first url",
                "$browser": "Firefox",
                "$os": "Mac",
            },
            timestamp="2020-01-03T01:01:01Z",
            person_id=person_id3,
        )

        create_person_id_override_by_distinct_id("distinctid1", "distinctid2", self.team.pk, 0)

        response = self._run(
            Filter(
                team=self.team,
                data={
                    "date_from": "2020-01-03",
                    "date_to": "2020-01-03",
                    "events": [{"id": "sign up", "name": "sign up", "math": "dau"}],
                },
            ),
            self.team,
        )
        self.assertEqual(response[0]["data"], [2.0])

        create_person_id_override_by_distinct_id("distinctid1", "distinctid3", self.team.pk, 1)

        response = self._run(
            Filter(
                team=self.team,
                data={
                    "date_from": "2020-01-03",
                    "date_to": "2020-01-03",
                    "events": [{"id": "sign up", "name": "sign up", "math": "dau"}],
                },
            ),
            self.team,
        )
        self.assertEqual(response[0]["data"], [1.0])

        create_person_id_override_by_distinct_id("distinctid1", "distinctid2", self.team.pk, 2)

        response = self._run(
            Filter(
                team=self.team,
                data={
                    "date_from": "2020-01-03",
                    "date_to": "2020-01-03",
                    "events": [{"id": "sign up", "name": "sign up", "math": "dau"}],
                },
            ),
            self.team,
        )
        self.assertEqual(response[0]["data"], [2.0])

    @also_test_with_materialized_columns(event_properties=["email", "name"], person_properties=["email", "name"])
    def test_ilike_regression_with_current_clickhouse_version(self):
        # CH upgrade to 22.3 has this problem: https://github.com/ClickHouse/ClickHouse/issues/36279
        # While we're waiting to upgrade to a newer version, a workaround is to set `optimize_move_to_prewhere = 0`
        # Only happens in the materialized version

        # The requirements to end up in this case is
        # 1. Having a JOIN
        # 2. Having multiple properties that filter on the same value

        with freeze_time("2020-01-04T13:01:01Z"):
            self._run(
                Filter(
                    team=self.team,
                    data={
                        "date_from": "-14d",
                        "events": [
                            {
                                "id": "watched movie",
                                "name": "watched movie",
                                "type": "events",
                                "order": 0,
                            }
                        ],
                        "properties": [
                            {
                                "key": "email",
                                "type": "event",
                                "value": "posthog.com",
                                "operator": "not_icontains",
                            },
                            {
                                "key": "name",
                                "type": "event",
                                "value": "posthog.com",
                                "operator": "not_icontains",
                            },
                            {
                                "key": "name",
                                "type": "person",
                                "value": "posthog.com",
                                "operator": "not_icontains",
                            },
                        ],
                    },
                ),
                self.team,
            )

    @also_test_with_person_on_events_v2
    @snapshot_clickhouse_queries
    def test_trends_count_per_user_average_daily(self):
        self._create_event_count_per_actor_events()

        daily_response = self._run(
            Filter(
                team=self.team,
                data={
                    "display": TRENDS_LINEAR,
                    "events": [{"id": "viewed video", "math": "avg_count_per_actor"}],
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                },
            ),
            self.team,
        )

        assert len(daily_response) == 1
        assert daily_response[0]["days"] == [
            "2020-01-01",
            "2020-01-02",
            "2020-01-03",
            "2020-01-04",
            "2020-01-05",
            "2020-01-06",
            "2020-01-07",
        ]
        assert daily_response[0]["data"] == [1.5, 0.0, 0.0, 1.0, 2.0, 0.0, 0.0]

    def test_trends_count_per_user_average_weekly(self):
        self._create_event_count_per_actor_events()

        weekly_response = self._run(
            Filter(
                team=self.team,
                data={
                    "display": TRENDS_LINEAR,
                    "events": [{"id": "viewed video", "math": "avg_count_per_actor"}],
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                    "interval": "week",
                },
            ),
            self.team,
        )

        assert len(weekly_response) == 1
        assert weekly_response[0]["days"] == ["2019-12-29", "2020-01-05"]
        assert weekly_response[0]["data"] == [1.3333333333333333, 2.0]

    @also_test_with_person_on_events_v2
    @snapshot_clickhouse_queries
    def test_trends_count_per_user_average_aggregated(self):
        self._create_event_count_per_actor_events()

        daily_response = self._run(
            Filter(
                team=self.team,
                data={
                    "display": TRENDS_TABLE,
                    "events": [{"id": "viewed video", "math": "avg_count_per_actor"}],
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                },
            ),
            self.team,
        )

        assert len(daily_response) == 1
        assert daily_response[0]["aggregated_value"] == 2.6666666666666665  # 8 events divided by 3 users

    def test_trends_count_per_user_maximum(self):
        self._create_event_count_per_actor_events()

        daily_response = self._run(
            Filter(
                team=self.team,
                data={
                    "display": TRENDS_LINEAR,
                    "events": [{"id": "viewed video", "math": "max_count_per_actor"}],
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                },
            ),
            self.team,
        )

        assert len(daily_response) == 1
        assert daily_response[0]["days"] == [
            "2020-01-01",
            "2020-01-02",
            "2020-01-03",
            "2020-01-04",
            "2020-01-05",
            "2020-01-06",
            "2020-01-07",
        ]
        assert daily_response[0]["data"] == [2.0, 0.0, 0.0, 1.0, 3.0, 0.0, 0.0]

    def test_trends_count_per_user_average_with_event_property_breakdown(self):
        self._create_event_count_per_actor_events()

        daily_response = self._run(
            Filter(
                team=self.team,
                data={
                    "display": TRENDS_LINEAR,
                    "breakdown": "color",
                    "events": [{"id": "viewed video", "math": "avg_count_per_actor"}],
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                },
            ),
            self.team,
        )

        assert len(daily_response) == 3
        assert daily_response[0]["breakdown_value"] == "red"
        assert daily_response[1]["breakdown_value"] == "blue"
        assert daily_response[2]["breakdown_value"] == "$$_posthog_breakdown_null_$$"
        assert daily_response[0]["days"] == [
            "2020-01-01",
            "2020-01-02",
            "2020-01-03",
            "2020-01-04",
            "2020-01-05",
            "2020-01-06",
            "2020-01-07",
        ]
        assert daily_response[1]["days"] == daily_response[0]["days"]
        assert daily_response[2]["days"] == daily_response[0]["days"]
        assert daily_response[0]["data"] == [1.0, 0.0, 0.0, 1.0, 2.0, 0.0, 0.0]  # red
        assert daily_response[1]["data"] == [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0]  # blue
        assert daily_response[2]["data"] == [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # $$_posthog_breakdown_null_$$

    def test_trends_count_per_user_average_with_person_property_breakdown(self):
        self._create_event_count_per_actor_events()

        daily_response = self._run(
            Filter(
                team=self.team,
                data={
                    "display": TRENDS_LINEAR,
                    "breakdown": "fruit",
                    "breakdown_type": "person",
                    "events": [{"id": "viewed video", "math": "avg_count_per_actor"}],
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                },
            ),
            self.team,
        )

        assert len(daily_response) == 2
        assert daily_response[0]["breakdown_value"] == "mango"
        assert daily_response[1]["breakdown_value"] == "tomato"
        assert daily_response[0]["days"] == [
            "2020-01-01",
            "2020-01-02",
            "2020-01-03",
            "2020-01-04",
            "2020-01-05",
            "2020-01-06",
            "2020-01-07",
        ]
        assert daily_response[1]["days"] == daily_response[0]["days"]
        assert daily_response[0]["data"] == [2.0, 0.0, 0.0, 1.0, 2.0, 0.0, 0.0]  # red
        assert daily_response[1]["data"] == [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # blue

    def test_trends_count_per_user_average_aggregated_with_event_property_breakdown(self):
        self._create_event_count_per_actor_events()

        daily_response = self._run(
            Filter(
                team=self.team,
                data={
                    "display": TRENDS_TABLE,
                    "breakdown": "color",
                    "events": [{"id": "viewed video", "math": "avg_count_per_actor"}],
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                },
            ),
            self.team,
        )

        assert len(daily_response) == 3
        assert daily_response[0]["breakdown_value"] == "red"
        assert daily_response[1]["breakdown_value"] == "blue"
        assert daily_response[2]["breakdown_value"] == "$$_posthog_breakdown_null_$$"
        assert daily_response[0]["aggregated_value"] == 2.0  # red
        assert daily_response[1]["aggregated_value"] == 1.0  # blue
        assert daily_response[2]["aggregated_value"] == 1.0  # $$_posthog_breakdown_null_$$

    @snapshot_clickhouse_queries
    def test_trends_count_per_user_average_aggregated_with_event_property_breakdown_with_sampling(self):
        self._create_event_count_per_actor_events()

        daily_response = self._run(
            Filter(
                team=self.team,
                data={
                    "sampling_factor": 1,
                    "display": TRENDS_TABLE,
                    "breakdown": "color",
                    "events": [{"id": "viewed video", "math": "avg_count_per_actor"}],
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                },
            ),
            self.team,
        )

        assert len(daily_response) == 3
        assert daily_response[0]["breakdown_value"] == "red"
        assert daily_response[1]["breakdown_value"] == "blue"
        assert daily_response[2]["breakdown_value"] == "$$_posthog_breakdown_null_$$"
        assert daily_response[0]["aggregated_value"] == 2.0  # red
        assert daily_response[1]["aggregated_value"] == 1.0  # blue
        assert daily_response[2]["aggregated_value"] == 1.0  # $$_posthog_breakdown_null_$$

    # TODO: Add support for avg_count by group indexes (see this Slack thread for more context: https://posthog.slack.com/archives/C0368RPHLQH/p1700484174374229)
    @pytest.mark.skip(reason="support for avg_count_per_actor not included yet")
    @snapshot_clickhouse_queries
    def test_trends_count_per_group_average_daily(self):
        self._create_event_count_per_actor_events()
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="shape", group_type_index=0
        )
        self._create_group(team_id=self.team.pk, group_type_index=0, group_key="bouba")
        self._create_group(team_id=self.team.pk, group_type_index=0, group_key="kiki")

        daily_response = self._run(
            Filter(
                team=self.team,
                data={
                    "display": TRENDS_LINEAR,
                    "events": [
                        {
                            "id": "viewed video",
                            "math": "avg_count_per_actor",
                            "math_group_type_index": 0,
                        }
                    ],
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                },
            ),
            self.team,
        )

        assert len(daily_response) == 1
        assert daily_response[0]["days"] == [
            "2020-01-01",
            "2020-01-02",
            "2020-01-03",
            "2020-01-04",
            "2020-01-05",
            "2020-01-06",
            "2020-01-07",
        ]
        assert daily_response[0]["data"] == [
            3.0,  # 3 group-assigned "viewed video" events by 2 persons / 1 group (bouba)
            0.0,  # No events at all
            0.0,  # No "viewed video" events
            1.0,  # 1 group-assigned "viewed video" event by 1 person / 1 group (kiki)
            1.5,  # 3 group-assigned "viewed video" events by 1 person / 2 groups (bouba, kiki)
            # The group-less event is ignored!
            0.0,  # No events at all
            0.0,  # No events at all
        ]

    # TODO: Add support for avg_count by group indexes (see this Slack thread for more context: https://posthog.slack.com/archives/C0368RPHLQH/p1700484174374229)
    @pytest.mark.skip(reason="support for avg_count_per_actor not included yet")
    @snapshot_clickhouse_queries
    def test_trends_count_per_group_average_aggregated(self):
        self._create_event_count_per_actor_events()
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="shape", group_type_index=0
        )
        self._create_group(team_id=self.team.pk, group_type_index=0, group_key="bouba")
        self._create_group(team_id=self.team.pk, group_type_index=0, group_key="kiki")

        daily_response = self._run(
            Filter(
                team=self.team,
                data={
                    "display": TRENDS_TABLE,
                    "events": [
                        {
                            "id": "viewed video",
                            "math": "avg_count_per_actor",
                            "math_group_type_index": 0,
                        }
                    ],
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                },
            ),
            self.team,
        )

        assert len(daily_response) == 1
        assert daily_response[0]["aggregated_value"] == 3.5  # 7 relevant events divided by 2 groups

    def test_trends_breakdown_timezone(self):
        self.team.timezone = "US/Pacific"
        self.team.save()
        self._create_event_count_per_actor_events()

        with freeze_time("2020-01-03 19:06:34"):
            self._create_person(team_id=self.team.pk, distinct_ids=["another_user"])
            self._create_event(
                team=self.team,
                event="viewed video",
                distinct_id="another_user",
                properties={"color": "orange"},
            )

        daily_response = self._run(
            Filter(
                team=self.team,
                data={
                    "display": TRENDS_LINEAR,
                    "events": [{"id": "viewed video", "math": "dau"}],
                    "breakdown": "color",
                    "date_from": "2020-01-01",
                    "date_to": "2020-03-07",
                    "interval": "month",
                },
            ),
            self.team,
        )

        # assert len(daily_response) == 4
        assert daily_response[0]["days"] == ["2020-01-01", "2020-02-01", "2020-03-01"]
        assert daily_response[1]["days"] == ["2020-01-01", "2020-02-01", "2020-03-01"]
        assert daily_response[2]["days"] == ["2020-01-01", "2020-02-01", "2020-03-01"]

    def _create_groups(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="company", group_type_index=1
        )

        self._create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )
        self._create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:6",
            properties={"industry": "technology"},
        )
        self._create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:7",
            properties={"industry": "finance"},
        )
        self._create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:10",
            properties={"industry": "finance"},
        )

    # TODO: Delete this test when moved to person-on-events
    def test_breakdown_with_filter_groups(self):
        self._create_groups()

        self._create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "oh", "$group_0": "org:7", "$group_1": "company:10"},
            timestamp="2020-01-02T12:00:00Z",
        )
        self._create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "uh", "$group_0": "org:5"},
            timestamp="2020-01-02T12:00:01Z",
        )
        self._create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "uh", "$group_0": "org:6"},
            timestamp="2020-01-02T12:00:02Z",
        )

        response = self._run(
            Filter(
                team=self.team,
                data={
                    "date_from": "2020-01-01T00:00:00Z",
                    "date_to": "2020-01-12T00:00:00Z",
                    "breakdown": "key",
                    "events": [
                        {
                            "id": "sign up",
                            "name": "sign up",
                            "type": "events",
                            "order": 0,
                        }
                    ],
                    "properties": [
                        {
                            "key": "industry",
                            "value": "finance",
                            "type": "group",
                            "group_type_index": 0,
                        }
                    ],
                },
            ),
            self.team,
        )

        self.assertEqual(len(response), 2)
        self.assertEqual(response[0]["breakdown_value"], "oh")
        self.assertEqual(response[0]["count"], 1)
        self.assertEqual(response[1]["breakdown_value"], "uh")
        self.assertEqual(response[1]["count"], 1)

    @snapshot_clickhouse_queries
    def test_breakdown_with_filter_groups_person_on_events(self):
        self._create_groups()

        self._create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "oh", "$group_0": "org:7", "$group_1": "company:10"},
            timestamp="2020-01-02T12:00:00Z",
        )
        self._create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "uh", "$group_0": "org:5"},
            timestamp="2020-01-02T12:00:01Z",
        )
        self._create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "uh", "$group_0": "org:6"},
            timestamp="2020-01-02T12:00:02Z",
        )

        response = self._run(
            Filter(
                team=self.team,
                data={
                    "date_from": "2020-01-01T00:00:00Z",
                    "date_to": "2020-01-12T00:00:00Z",
                    "breakdown": "key",
                    "events": [
                        {
                            "id": "sign up",
                            "name": "sign up",
                            "type": "events",
                            "order": 0,
                        }
                    ],
                    "properties": [
                        {
                            "key": "industry",
                            "value": "finance",
                            "type": "group",
                            "group_type_index": 0,
                        }
                    ],
                },
            ),
            self.team,
        )

        self.assertEqual(len(response), 2)
        self.assertEqual(response[0]["breakdown_value"], "oh")
        self.assertEqual(response[0]["count"], 1)
        self.assertEqual(response[1]["breakdown_value"], "uh")
        self.assertEqual(response[1]["count"], 1)

    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=True)
    @snapshot_clickhouse_queries
    def test_breakdown_with_filter_groups_person_on_events_v2(self):
        self._create_groups()

        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        self._create_event(
            event="sign up",
            distinct_id="test_breakdown_d1",
            team=self.team,
            properties={"key": "oh", "$group_0": "org:7", "$group_1": "company:10"},
            timestamp="2020-01-02T12:00:00Z",
            person_id=id1,
        )
        self._create_event(
            event="sign up",
            distinct_id="test_breakdown_d1",
            team=self.team,
            properties={"key": "uh", "$group_0": "org:5"},
            timestamp="2020-01-02T12:00:01Z",
            person_id=id1,
        )
        self._create_event(
            event="sign up",
            distinct_id="test_breakdown_d1",
            team=self.team,
            properties={"key": "uh", "$group_0": "org:6"},
            timestamp="2020-01-02T12:00:02Z",
            person_id=id1,
        )
        self._create_event(
            event="sign up",
            distinct_id="test_breakdown_d2",
            team=self.team,
            properties={"key": "uh", "$group_0": "org:6"},
            timestamp="2020-01-02T12:00:02Z",
            person_id=id2,
        )

        create_person_id_override_by_distinct_id("test_breakdown_d1", "test_breakdown_d2", self.team.pk)
        response = self._run(
            Filter(
                team=self.team,
                data={
                    "date_from": "2020-01-01T00:00:00Z",
                    "date_to": "2020-01-12T00:00:00Z",
                    "breakdown": "key",
                    "events": [
                        {
                            "id": "sign up",
                            "name": "sign up",
                            "type": "events",
                            "order": 0,
                            "math": "dau",
                        }
                    ],
                    "properties": [
                        {
                            "key": "industry",
                            "value": "finance",
                            "type": "group",
                            "group_type_index": 0,
                        }
                    ],
                },
            ),
            self.team,
        )

        self.assertEqual(len(response), 2)
        self.assertEqual(response[0]["breakdown_value"], "oh")
        self.assertEqual(response[0]["count"], 1)
        self.assertEqual(response[1]["breakdown_value"], "uh")
        self.assertEqual(response[1]["count"], 1)

    # TODO: Delete this test when moved to person-on-events
    def test_breakdown_by_group_props(self):
        self._create_groups()

        journey = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 12),
                    "properties": {"$group_0": "org:5"},
                    "group0_properties": {"industry": "finance"},
                },
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 13),
                    "properties": {"$group_0": "org:6"},
                    "group0_properties": {"industry": "technology"},
                },
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 15),
                    "properties": {"$group_0": "org:7", "$group_1": "company:10"},
                    "group0_properties": {"industry": "finance"},
                    "group1_properties": {"industry": "finance"},
                },
            ]
        }

        journeys_for(events_by_person=journey, team=self.team)

        filter = Filter(
            team=self.team,
            data={
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12",
                "breakdown": "industry",
                "breakdown_type": "group",
                "breakdown_group_type_index": 0,
                "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0}],
            },
        )
        response = self._run(filter, self.team)

        self.assertEqual(len(response), 2)
        self.assertEqual(response[0]["breakdown_value"], "finance")
        self.assertEqual(response[0]["count"], 2)
        self.assertEqual(response[1]["breakdown_value"], "technology")
        self.assertEqual(response[1]["count"], 1)

        res = self._get_actors(
            filters=filter.to_dict(),
            team=self.team,
            series=0,
            breakdown="technology",
            day="2020-01-02",
            includeRecordings=True,
        )

        self.assertEqual(res[0][0]["distinct_ids"], ["person1"])

    @freeze_time("2020-01-01")
    @snapshot_clickhouse_queries
    def test_breakdown_by_group_props_person_on_events(self):
        self._create_groups()

        journey = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 12),
                    "properties": {"$group_0": "org:5"},
                    "group0_properties": {"industry": "finance"},
                },
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 13),
                    "properties": {"$group_0": "org:6"},
                    "group0_properties": {"industry": "technology"},
                },
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 15),
                    "properties": {"$group_0": "org:7", "$group_1": "company:10"},
                    "group0_properties": {"industry": "finance"},
                    "group1_properties": {"industry": "finance"},
                },
            ]
        }

        journeys_for(events_by_person=journey, team=self.team)

        filter = Filter(
            team=self.team,
            data={
                "date_from": "2020-01-01",
                "date_to": "2020-01-12",
                "breakdown": "industry",
                "breakdown_type": "group",
                "breakdown_group_type_index": 0,
                "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0}],
            },
        )

        with override_instance_config("PERSON_ON_EVENTS_ENABLED", True):
            response = self._run(filter, self.team)

            self.assertEqual(len(response), 2)
            self.assertEqual(response[0]["breakdown_value"], "finance")
            self.assertEqual(response[0]["count"], 2)
            self.assertEqual(response[1]["breakdown_value"], "technology")
            self.assertEqual(response[1]["count"], 1)

            res = self._get_actors(
                filters=filter.to_dict(),
                team=self.team,
                series=0,
                breakdown="technology",
                day="2020-01-02",
                includeRecordings=True,
            )

            self.assertEqual(res[0][0]["distinct_ids"], ["person1"])

    # TODO: Delete this test when moved to person-on-events
    def test_breakdown_by_group_props_with_person_filter(self):
        self._create_groups()

        Person.objects.create(team_id=self.team.pk, distinct_ids=["person1"], properties={"key": "value"})

        self._create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:5"},
            timestamp="2020-01-02T12:00:00Z",
            person_properties={"key": "value"},
            group0_properties={"industry": "finance"},
        )
        self._create_event(
            event="sign up",
            distinct_id="person2",
            team=self.team,
            properties={"$group_0": "org:6"},
            timestamp="2020-01-02T12:00:00Z",
            person_properties={},
            group0_properties={"industry": "technology"},
        )

        filter = Filter(
            team=self.team,
            data={
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "breakdown": "industry",
                "breakdown_type": "group",
                "breakdown_group_type_index": 0,
                "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0}],
                "properties": [{"key": "key", "value": "value", "type": "person"}],
            },
        )

        response = self._run(filter, self.team)

        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]["breakdown_value"], "finance")
        self.assertEqual(response[0]["count"], 1)

    # TODO: Delete this test when moved to person-on-events
    def test_filtering_with_group_props(self):
        self._create_groups()

        Person.objects.create(team_id=self.team.pk, distinct_ids=["person1"], properties={"key": "value"})
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            timestamp="2020-01-02T12:00:00Z",
        )
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:5"},
            timestamp="2020-01-02T12:00:00Z",
        )
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:6"},
            timestamp="2020-01-02T12:00:00Z",
        )
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:6", "$group_1": "company:10"},
            timestamp="2020-01-02T12:00:00Z",
        )

        filter = Filter(
            team=self.team,
            data={
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "events": [{"id": "$pageview", "type": "events", "order": 0}],
                "properties": [
                    {
                        "key": "industry",
                        "value": "finance",
                        "type": "group",
                        "group_type_index": 0,
                    },
                    {"key": "key", "value": "value", "type": "person"},
                ],
            },
        )

        response = self._run(filter, self.team)
        self.assertEqual(response[0]["count"], 1)

    def test_filtering_with_group_props_event_with_no_group_data(self):
        self._create_groups()

        Person.objects.create(team_id=self.team.pk, distinct_ids=["person1"], properties={"key": "value"})
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            timestamp="2020-01-02T12:00:00Z",
        )
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            timestamp="2020-01-02T12:00:00Z",
        )
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            timestamp="2020-01-02T12:00:00Z",
        )
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            timestamp="2020-01-02T12:00:00Z",
        )

        filter = Filter(
            team=self.team,
            data={
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "events": [{"id": "$pageview", "type": "events", "order": 0}],
                "properties": [
                    {
                        "key": "industry",
                        "operator": "is_not",
                        "value": "textiles",
                        "type": "group",
                        "group_type_index": 0,
                    },
                    {"key": "key", "value": "value", "type": "person"},
                ],
            },
        )

        response = self._run(filter, self.team)

        # we include all 4 events even though they do not have an associated group since the filter is a negative
        # i.e. "industry is not textiles" includes both events associated with a group that has the property "industry"
        # set to a value other than textiles AND events with no group at all
        self.assertEqual(response[0]["count"], 4)

    @snapshot_clickhouse_queries
    def test_breakdown_by_group_props_with_person_filter_person_on_events(self):
        self._create_groups()

        Person.objects.create(team_id=self.team.pk, distinct_ids=["person1"], properties={"key": "value"})

        self._create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:5"},
            timestamp="2020-01-02T12:00:00Z",
            person_properties={"key": "value"},
            group0_properties={"industry": "finance"},
        )
        self._create_event(
            event="sign up",
            distinct_id="person2",
            team=self.team,
            properties={"$group_0": "org:6"},
            timestamp="2020-01-02T12:00:00Z",
            person_properties={},
            group0_properties={"industry": "technology"},
        )

        filter = Filter(
            team=self.team,
            data={
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "breakdown": "industry",
                "breakdown_type": "group",
                "breakdown_group_type_index": 0,
                "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0}],
                "properties": [{"key": "key", "value": "value", "type": "person"}],
            },
        )

        with override_instance_config("PERSON_ON_EVENTS_ENABLED", True):
            response = self._run(filter, self.team)

            self.assertEqual(len(response), 1)
            self.assertEqual(response[0]["breakdown_value"], "finance")
            self.assertEqual(response[0]["count"], 1)

    @snapshot_clickhouse_queries
    def test_filtering_with_group_props_person_on_events(self):
        self._create_groups()

        Person.objects.create(team_id=self.team.pk, distinct_ids=["person1"], properties={"key": "value"})
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            timestamp="2020-01-02T12:00:00Z",
        )
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:5"},
            timestamp="2020-01-02T12:00:00Z",
        )
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:6"},
            timestamp="2020-01-02T12:00:00Z",
        )
        self._create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:6", "$group_1": "company:10"},
            timestamp="2020-01-02T12:00:00Z",
        )

        filter = Filter(
            team=self.team,
            data={
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "events": [{"id": "$pageview", "type": "events", "order": 0}],
                "properties": [
                    {
                        "key": "industry",
                        "value": "finance",
                        "type": "group",
                        "group_type_index": 0,
                    },
                    {"key": "key", "value": "value", "type": "person"},
                ],
            },
        )

        with override_instance_config("PERSON_ON_EVENTS_ENABLED", True):
            response = self._run(filter, self.team)
            self.assertEqual(response[0]["count"], 1)

    @freeze_time("2020-01-01")
    @snapshot_clickhouse_queries
    def test_filtering_by_multiple_groups_person_on_events(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="company", group_type_index=2
        )

        self._create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )
        self._create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:6",
            properties={"industry": "technology"},
        )
        self._create_group(
            team_id=self.team.pk,
            group_type_index=2,
            group_key="company:5",
            properties={"name": "five"},
        )
        self._create_group(
            team_id=self.team.pk,
            group_type_index=2,
            group_key="company:6",
            properties={"name": "six"},
        )

        journey = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 12),
                    "properties": {"$group_0": "org:5", "$group_2": "company:6"},
                },
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 12, 30),
                    "properties": {"$group_2": "company:6"},
                },
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 13),
                    "properties": {"$group_0": "org:6"},
                },
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 3, 15),
                    "properties": {"$group_2": "company:5"},
                },
            ]
        }

        journeys_for(events_by_person=journey, team=self.team)

        filter = Filter(
            team=self.team,
            data={
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12",
                "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0}],
                "properties": [
                    {
                        "key": "industry",
                        "value": "finance",
                        "type": "group",
                        "group_type_index": 0,
                    },
                    {
                        "key": "name",
                        "value": "six",
                        "type": "group",
                        "group_type_index": 2,
                    },
                ],
            },
        )

        with override_instance_config("PERSON_ON_EVENTS_ENABLED", True):
            response = self._run(filter, self.team)

            self.assertEqual(len(response), 1)
            self.assertEqual(response[0]["count"], 1)
            self.assertEqual(
                response[0]["data"],
                [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )

            res = self._get_actors(
                filters=filter.to_dict(), team=self.team, series=0, day="2020-01-02", includeRecordings=True
            )

            self.assertEqual(res[0][0]["distinct_ids"], ["person1"])

    def test_yesterday_with_hourly_interval(self):
        journey = {
            "person1": [
                # hour times events for each hour in the day
                {"event": "sign up", "timestamp": datetime(2020, 1, 2, hour, 30)}
                for hour in range(24)
                for _ in range(hour)
            ]
        }

        journeys_for(events_by_person=journey, team=self.team)

        filter = Filter(
            team=self.team,
            data={
                "date_from": "-1dStart",
                "date_to": "-1dEnd",
                "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0}],
                "interval": "hour",
            },
        )

        with freeze_time("2020-01-03 13:06:02"):
            response = self._run(filter, self.team)

        self.assertEqual(len(response), 1)
        self.assertEqual(
            response[0]["data"],
            [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
        )
