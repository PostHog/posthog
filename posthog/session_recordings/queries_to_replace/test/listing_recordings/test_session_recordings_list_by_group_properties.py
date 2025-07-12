from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.log_entries import TRUNCATE_LOG_ENTRIES_TABLE_SQL
from posthog.models import Person, GroupTypeMapping
from posthog.models.group.util import create_group
from posthog.session_recordings.queries_to_replace.test.listing_recordings.test_utils import (
    assert_query_matches_session_ids,
)
from posthog.session_recordings.queries_to_replace.test.session_replay_sql import (
    produce_replay_summary,
)
from posthog.session_recordings.sql.session_replay_event_sql import (
    TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    snapshot_clickhouse_queries,
    _create_event,
)


@freeze_time("2020-01-01T13:46:23")
class TestSessionRecordingsListByGroupProperties(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        sync_execute(TRUNCATE_LOG_ENTRIES_TABLE_SQL)

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

    @snapshot_clickhouse_queries
    def test_filter_with_group_properties(self) -> None:
        # there is one person
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"], properties={"$browser": "test"})

        # there are two groups
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="company", group_type_index=1
        )
        # each has an instance with properties
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:1",
            properties={"another": "value"},
        )
        # there are events in session 1 matching org5
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            session_id="session_1",
            timestamp="2019-12-30T12:00:00Z",
            properties={"$group_0": "org:5", "$group_1": "company:12", "$session_id": "session_1"},
        )
        # there are events in session 2 matching company:1
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            session_id="session_2",
            timestamp="2019-12-30T12:00:00Z",
            # without events
            properties={"$group_0": "org:40", "$group_1": "company:1", "$session_id": "session_2"},
        )

        produce_replay_summary(
            distinct_id="p1",
            session_id="session_1",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )

        produce_replay_summary(
            distinct_id="p1",
            session_id="session_2",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )

        self._assert_query_matches_session_ids(
            {
                "properties": [
                    # group type index 1 is the company group
                    # it can only match session 2
                    # and only with the property "another" with value "value"
                    {"key": "another", "value": ["value"], "operator": "exact", "type": "group", "group_type_index": 1}
                ]
            },
            ["session_2"],
        )

        self._assert_query_matches_session_ids(
            {
                "properties": [
                    # group type index 1 is the company group
                    # it can only match session 2
                    # and only with the property "another" with value "value"
                    {
                        "key": "another",
                        "value": ["difference"],
                        "operator": "exact",
                        "type": "group",
                        "group_type_index": 1,
                    }
                ]
            },
            [],
        )

        self._assert_query_matches_session_ids(
            {
                "properties": [
                    # group type index 1 is the company group
                    # it can only match session 2
                    # and only with the property "another" with value "value"
                    {
                        "key": "difference",
                        "value": ["value"],
                        "operator": "exact",
                        "type": "group",
                        "group_type_index": 1,
                    }
                ]
            },
            [],
        )

        self._assert_query_matches_session_ids(
            {
                "properties": [
                    # group type index 0 is the organization group
                    # it can only match session 1
                    # and only with the property "industry" with value "finance"
                    {
                        "key": "industry",
                        "value": ["finance"],
                        "operator": "exact",
                        "type": "group",
                        "group_type_index": 0,
                    }
                ]
            },
            ["session_1"],
        )

        self._assert_query_matches_session_ids(
            {
                "properties": [
                    # group type index 0 is the organization group
                    # it can only match session 1
                    # and only with the property "industry" with value "finance"
                    {
                        "key": "industry",
                        "value": ["difference"],
                        "operator": "exact",
                        "type": "group",
                        "group_type_index": 0,
                    }
                ]
            },
            [],
        )

        self._assert_query_matches_session_ids(
            {
                "properties": [
                    # group type index 0 is the organization group
                    # it can only match session 1
                    # and only with the property "industry" with value "finance"
                    {
                        "key": "difference",
                        "value": ["finance"],
                        "operator": "exact",
                        "type": "group",
                        "group_type_index": 0,
                    }
                ]
            },
            [],
        )
