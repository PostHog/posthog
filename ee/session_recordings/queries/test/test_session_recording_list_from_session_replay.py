from unittest import mock

from ee.clickhouse.materialized_columns.columns import materialize
from posthog.models.filters import SessionRecordingsFilter
from posthog.session_recordings.queries.session_recording_list_from_replay_summary import (
    SessionRecordingListFromReplaySummary,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


class TestClickhouseSessionRecordingsListFromSessionReplay(ClickhouseTestMixin, APIBaseTest):
    def test_wat(self) -> None:
        # person on events running?
        # person column materialized on events table
        # session replay filter for person properties
        # query should use events table column to avoid the join on persons
        # e.g. properties: [{"key":"rgInternal","value":["false"],"operator":"exact","type":"person"}]

        materialize("events", "person_prop", table_column="person_properties")

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

        # the unmaterialized column should query should not be used
        assert (
            "has(%(vperson_filter_pre__0)s, replaceRegexpAll(JSONExtractRaw(properties, %(kperson_filter_pre__0)s)"
            not in generated_query
        ), generated_query
        assert "mat_pp_rgInternal" in generated_query, generated_query
