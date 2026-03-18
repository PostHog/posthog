from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.log_entries import TRUNCATE_LOG_ENTRIES_TABLE_SQL
from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.listing_recordings.test_utils import (
    assert_query_matches_session_ids,
    create_event,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL


@freeze_time("2021-01-01T13:46:23")
class TestSessionRecordingsListOperandsQueries(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        sync_execute(TRUNCATE_LOG_ENTRIES_TABLE_SQL)

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

    # wrap the util so we don't have to pass team every time
    def _assert_query_matches_session_ids(
        self, query: dict | None, expected: list[str], sort_results_when_asserting: bool = True
    ) -> None:
        assert_query_matches_session_ids(
            team=self.team, query=query, expected=expected, sort_results_when_asserting=sort_results_when_asserting
        )

    @property
    def an_hour_ago(self):
        return (now() - relativedelta(hours=1)).replace(microsecond=0, second=0)

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


@freeze_time("2021-01-01T13:46:23")
class TestSessionRecordingsNegativeFiltersWithMultipleEvents(ClickhouseTestMixin, APIBaseTest):
    """
    Negative filters should match sessions where NO events match the positive condition.
    A session with mixed events (some matching, some not) should be excluded.
    """

    def setUp(self):
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        sync_execute(TRUNCATE_LOG_ENTRIES_TABLE_SQL)

    @property
    def an_hour_ago(self):
        return (now() - relativedelta(hours=1)).replace(microsecond=0, second=0)

    def _a_session_with_multiple_pageviews(self, pageview_properties_list: list[dict]) -> str:
        session_id = str(uuid7())
        user_id = str(uuid7())

        produce_replay_summary(
            distinct_id=user_id,
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )

        for i, props in enumerate(pageview_properties_list):
            create_event(
                team=self.team,
                distinct_id=user_id,
                timestamp=self.an_hour_ago + relativedelta(minutes=i),
                properties={"$session_id": session_id, "$window_id": "1", **props},
            )

        return session_id

    @parameterized.expand(
        [
            (
                "not_icontains_entity_property",
                {"$pathname": "/target-page"},
                {"$pathname": "/other-page"},
                {
                    "operand": "AND",
                    "events": [
                        {
                            "id": "$pageview",
                            "name": "$pageview",
                            "type": "events",
                            "properties": [
                                {"key": "$pathname", "type": "event", "value": "target", "operator": "not_icontains"}
                            ],
                        }
                    ],
                },
            ),
            (
                "is_not_entity_property",
                {"vip": "true"},
                {"vip": "false"},
                {
                    "operand": "AND",
                    "events": [
                        {
                            "id": "$pageview",
                            "name": "$pageview",
                            "type": "events",
                            "properties": [{"key": "vip", "type": "event", "value": ["true"], "operator": "is_not"}],
                        }
                    ],
                },
            ),
            (
                "not_icontains_top_level_property",
                {"email": "test@posthog.com"},
                {"email": "test@gmail.com"},
                {"properties": [{"key": "email", "type": "event", "value": "posthog", "operator": "not_icontains"}]},
            ),
        ]
    )
    def test_negative_filter_excludes_session_with_any_matching_event(
        self, _name: str, matching_props: dict, non_matching_props: dict, query: dict
    ):
        _mixed_session = self._a_session_with_multiple_pageviews([matching_props, non_matching_props])
        clean_session = self._a_session_with_multiple_pageviews([non_matching_props, non_matching_props])

        assert_query_matches_session_ids(team=self.team, query=query, expected=[clean_session])
