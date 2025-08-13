from freezegun import freeze_time

from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.listing_recordings.test_utils import create_event
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.queries.test.listing_recordings.base_test_session_recordings_list import (
    BaseTestSessionRecordingsList,
)
from posthog.test.base import snapshot_clickhouse_queries


@freeze_time("2021-01-01T13:46:23")
class TestSessionRecordingsListOperandsQueries(BaseTestSessionRecordingsList):
    def setUp(self):
        super().setUp()

        self.target_vip_session = self._a_session_with_properties_on_pageviews(
            {"$pathname": "/my-target-page", "vip": True}
        )
        self.target_non_vip_session = self._a_session_with_properties_on_pageviews(
            {"$pathname": "/my-target-page", "vip": False}
        )
        self.non_target_vip_session = self._a_session_with_properties_on_pageviews(
            {"$pathname": "/my-other-page", "vip": True}
        )
        self.non_target_non_vip_session = self._a_session_with_properties_on_pageviews(
            {"$pathname": "/my-other-page", "vip": False}
        )

    def _a_session_with_properties_on_pageviews(self, pageViewProperties: dict) -> str:
        session_id = str(uuid7())
        user_id = str(uuid7())

        produce_replay_summary(
            distinct_id=user_id,
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )

        create_event(
            team=self.team,
            distinct_id=user_id,
            timestamp=self.an_hour_ago,
            properties={"$session_id": session_id, "$window_id": "1", **pageViewProperties},
        )

        return session_id

    @snapshot_clickhouse_queries
    def test_multiple_event_filters_and_ed(self):
        self._assert_query_matches_session_ids(
            {
                "operand": "AND",
                "events": [
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "properties": [{"key": "vip", "type": "event", "value": ["true"], "operator": "exact"}],
                    },
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "properties": [
                            {"key": "$pathname", "type": "event", "value": "target", "operator": "icontains"}
                        ],
                    },
                ],
            },
            [self.target_vip_session],
        )

    @snapshot_clickhouse_queries
    def test_multiple_event_filters_or_ed(self):
        self._assert_query_matches_session_ids(
            {
                "operand": "OR",
                "events": [
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "properties": [{"key": "vip", "type": "event", "value": ["true"], "operator": "exact"}],
                    },
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "properties": [
                            {"key": "$pathname", "type": "event", "value": "target", "operator": "icontains"}
                        ],
                    },
                ],
            },
            [self.target_vip_session, self.target_non_vip_session, self.non_target_vip_session],
        )

    @snapshot_clickhouse_queries
    def test_positive_and_negative_anded(self):
        self._assert_query_matches_session_ids(
            {
                "operand": "AND",
                "events": [
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "properties": [{"key": "vip", "type": "event", "value": ["true"], "operator": "exact"}],
                    },
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "properties": [
                            {"key": "$pathname", "type": "event", "value": "target", "operator": "not_icontains"}
                        ],
                    },
                ],
            },
            [self.non_target_vip_session],
        )

    @snapshot_clickhouse_queries
    def test_two_negative_anded(self):
        self._assert_query_matches_session_ids(
            {
                "operand": "AND",
                "events": [
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "properties": [{"key": "vip", "type": "event", "value": ["true"], "operator": "is_not"}],
                    },
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "properties": [
                            {"key": "$pathname", "type": "event", "value": "target", "operator": "not_icontains"}
                        ],
                    },
                ],
            },
            [self.non_target_non_vip_session],
        )

    @snapshot_clickhouse_queries
    def test_two_negative_ORed(self):
        self._assert_query_matches_session_ids(
            {
                "operand": "OR",
                "events": [
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "properties": [{"key": "vip", "type": "event", "value": ["true"], "operator": "is_not"}],
                    },
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "properties": [
                            {"key": "$pathname", "type": "event", "value": "target", "operator": "not_icontains"}
                        ],
                    },
                ],
            },
            [self.non_target_non_vip_session, self.non_target_vip_session, self.target_non_vip_session],
        )
