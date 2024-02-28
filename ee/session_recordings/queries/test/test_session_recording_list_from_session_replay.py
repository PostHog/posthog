from unittest import mock

from django.test import override_settings

from ee.clickhouse.materialized_columns.columns import materialize
from ee.clickhouse.queries.column_optimizer import EnterpriseColumnOptimizer
from posthog.models.filters import SessionRecordingsFilter
from posthog.models.property.util import get_property_string_expr
from posthog.session_recordings.queries.session_recording_list_from_replay_summary import (
    SessionRecordingListFromReplaySummary,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from posthog.utils import PersonOnEventsMode


class TestClickhouseSessionRecordingsListFromSessionReplay(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def setUp(self):
        super().setUp()

    @override_settings(
        PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=True, ALLOW_DENORMALIZED_PROPS_IN_LISTING=True
    )
    def test_wat(self) -> None:
        # query should use events table column to avoid the join on persons

        assert self.team.person_on_events_mode == PersonOnEventsMode.V2_ENABLED
        materialize("events", "rgInternal", table_column="person_properties")

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "properties": [
                    {
                        "key": "rgInternal",
                        "value": ["false"],
                        "operator": "exact",
                        "type": "person",
                    }
                ]
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        [generated_query, query_params] = session_recording_list_instance.get_query()
        assert query_params == {
            "clamped_to_storage_ttl": mock.ANY,
            "end_time": mock.ANY,
            "event_end_time": mock.ANY,
            "event_names": [],
            "event_start_time": mock.ANY,
            "kglobal_0": "rgInternal",
            "limit": 51,
            "offset": 0,
            "start_time": mock.ANY,
            "team_id": self.team.id,
            "vglobal_0": ["false"],
        }

        ee_optimizer = EnterpriseColumnOptimizer(
            filter.shallow_clone(overrides={}),
            self.team.id,
        )
        # if we were to use the person table, we simply extract from properties
        assert ee_optimizer.person_columns_to_query == {"properties"}
        # whereas person on events stores properties on the events table as person_properties,
        # and we have materialized the property, so its returned rather than person_properties
        assert ee_optimizer.person_on_event_columns_to_query == {"mat_pp_rgInternal"}

        x = get_property_string_expr(
            table="events",  # need to choose this based on PoE mode I guess!
            property_name="rgInternal",
            var="wat",
            column="person_properties",
            allow_denormalized_props=True,
            table_alias=None,
            materialised_table_column="person_properties",
        )
        assert x == (
            '"mat_pp_rgInternal"',
            # the column was materialized, so we can query it directly not extract from properties
            True,  # true here is saying that a materialized column was picked
        )

        # the unmaterialized column should query should not be used
        assert (
            "has(%(vperson_filter_pre__0)s, replaceRegexpAll(JSONExtractRaw(properties, %(kperson_filter_pre__0)s)"
            not in generated_query
        )
        assert 'AND (  has(%(vglobal_0)s, "mat_pp_rgInternal"))' in generated_query
        self.assertQueryMatchesSnapshot(generated_query)
