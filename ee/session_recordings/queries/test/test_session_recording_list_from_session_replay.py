from unittest import mock

from django.test import override_settings

from ee.clickhouse.materialized_columns.columns import materialize
from posthog.models.filters import SessionRecordingsFilter
from posthog.session_recordings.queries.session_recording_list_from_replay_summary import (
    SessionRecordingListFromReplaySummary,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from posthog.utils import PersonOnEventsMode


class TestClickhouseSessionRecordingsListFromSessionReplay(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    @override_settings(
        PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False, ALLOW_DENORMALIZED_PROPS_IN_LISTING=False
    )
    def test_poe_v1_still_falls_back_to_person_subquery(self) -> None:
        assert self.team.person_on_events_mode == PersonOnEventsMode.V1_ENABLED
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
            "kperson_filter_pre__0": "rgInternal",
            "kpersonquery_person_filter_fin__0": "rgInternal",
            "limit": 51,
            "offset": 0,
            "person_uuid": None,
            "start_time": mock.ANY,
            "team_id": self.team.id,
            "vperson_filter_pre__0": ["false"],
            "vpersonquery_person_filter_fin__0": ["false"],
        }

        # the unmaterialized column should query should be used
        assert (
            "has(%(vperson_filter_pre__0)s, replaceRegexpAll(JSONExtractRaw(properties, %(kperson_filter_pre__0)s)"
            in generated_query
        )
        # materialized column should not be used
        assert 'AND (  has(%(vglobal_0)s, "mat_pp_rgInternal"))' not in generated_query
        self.assertQueryMatchesSnapshot(generated_query)

    @override_settings(
        PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False, ALLOW_DENORMALIZED_PROPS_IN_LISTING=False
    )
    def test_poe_being_unavailable_we_fall_back_to_person_subquery(self) -> None:
        assert self.team.person_on_events_mode == PersonOnEventsMode.DISABLED
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
            "kperson_filter_pre__0": "rgInternal",
            "kpersonquery_person_filter_fin__0": "rgInternal",
            "limit": 51,
            "offset": 0,
            "person_uuid": None,
            "start_time": mock.ANY,
            "team_id": self.team.id,
            "vperson_filter_pre__0": ["false"],
            "vpersonquery_person_filter_fin__0": ["false"],
        }

        # the unmaterialized column should query should be used
        assert (
            "has(%(vperson_filter_pre__0)s, replaceRegexpAll(JSONExtractRaw(properties, %(kperson_filter_pre__0)s)"
            in generated_query
        )
        # materialized column should not be used
        assert 'AND (  has(%(vglobal_0)s, "mat_pp_rgInternal"))' not in generated_query
        self.assertQueryMatchesSnapshot(generated_query)

    @override_settings(
        PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=True, ALLOW_DENORMALIZED_PROPS_IN_LISTING=False
    )
    def test_allow_denormalised_props_fix_does_not_stop_all_poe_processing(self) -> None:
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

        # the unmaterialized column should query should not be used
        assert (
            "has(%(vperson_filter_pre__0)s, replaceRegexpAll(JSONExtractRaw(properties, %(kperson_filter_pre__0)s)"
            not in generated_query
        )
        assert 'AND (  has(%(vglobal_0)s, "mat_pp_rgInternal"))' in generated_query
        self.assertQueryMatchesSnapshot(generated_query)

    @override_settings(
        PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=True, ALLOW_DENORMALIZED_PROPS_IN_LISTING=True
    )
    def test_poe_v2_available_person_properties_are_used_in_replay_listing(self) -> None:
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

        # the unmaterialized column should query should not be used
        assert (
            "has(%(vperson_filter_pre__0)s, replaceRegexpAll(JSONExtractRaw(properties, %(kperson_filter_pre__0)s)"
            not in generated_query
        )
        assert 'AND (  has(%(vglobal_0)s, "mat_pp_rgInternal"))' in generated_query
        self.assertQueryMatchesSnapshot(generated_query)
