import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries
from unittest.mock import patch

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from parameterized import parameterized

from posthog.schema import PersonsOnEventsMode

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.log_entries import TRUNCATE_LOG_ENTRIES_TABLE_SQL
from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.listing_recordings.test_utils import (
    assert_query_matches_session_ids,
    create_event,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL
from posthog.test.persons import create_person

from products.cohorts.backend.models.cohort import Cohort


def exclusions_under_or_flag_on():
    return patch("posthog.session_recordings.queries.utils.feature_enabled_or_false", return_value=True)


PAGEVIEW_WITH_VIP = {
    "id": "$pageview",
    "name": "$pageview",
    "type": "events",
    "properties": [{"key": "vip", "type": "event", "value": ["true"], "operator": "exact"}],
}
PAGEVIEW_ON_TARGET_PAGE = {
    "id": "$pageview",
    "name": "$pageview",
    "type": "events",
    "properties": [{"key": "$pathname", "type": "event", "value": "target", "operator": "icontains"}],
}
PATHNAME_NOT_OTHER = {"key": "$pathname", "type": "event", "value": "other", "operator": "not_icontains"}

# the filter shape reported in #41687: two different events, the first carrying two of its own properties
FLAG_CALLED_WITH_PROPERTIES = {
    "id": "$feature_flag_called",
    "name": "$feature_flag_called",
    "type": "events",
    "properties": [
        {"key": "$feature_flag_response", "type": "event", "value": ["test"], "operator": "exact"},
        {"key": "$feature_flag", "type": "event", "value": "onboarding-questionnaire", "operator": "exact"},
    ],
}
ONBOARDING_INITIALIZED = {
    "id": "onboarding-initialized",
    "name": "onboarding-initialized",
    "type": "events",
}


@time_machine.travel("2021-01-01T13:46:23", tick=False)
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

    @snapshot_clickhouse_queries
    @exclusions_under_or_flag_on()
    def test_two_negative_ORed_with_exclusions_under_or(self, _flag):
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
            [self.non_target_non_vip_session],
        )

    @snapshot_clickhouse_queries
    @exclusions_under_or_flag_on()
    def test_two_positive_and_one_negative_ORed_with_exclusions_under_or(self, _flag):
        self._assert_query_matches_session_ids(
            {
                "operand": "OR",
                "events": [PAGEVIEW_WITH_VIP, PAGEVIEW_ON_TARGET_PAGE],
                "properties": [PATHNAME_NOT_OTHER],
            },
            [self.target_vip_session, self.target_non_vip_session],
        )

    def _a_session_with_named_events(self, events: list[tuple[str, dict]], duration_seconds: int = 30) -> str:
        session_id = str(uuid7())
        user_id = str(uuid7())

        produce_replay_summary(
            distinct_id=user_id,
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            last_timestamp=self.an_hour_ago + relativedelta(seconds=duration_seconds),
            team_id=self.team.id,
        )

        for event_name, properties in events:
            create_event(
                team=self.team,
                distinct_id=user_id,
                timestamp=self.an_hour_ago,
                event_name=event_name,
                properties={"$session_id": session_id, "$window_id": "1", **properties},
            )

        return session_id

    def _sessions_for_two_distinct_event_filters(self) -> tuple[str, str, str]:
        matching_flag_event = (
            "$feature_flag_called",
            {"$feature_flag_response": "test", "$feature_flag": "onboarding-questionnaire"},
        )
        both = self._a_session_with_named_events([matching_flag_event, ("onboarding-initialized", {})])
        only_flag = self._a_session_with_named_events([matching_flag_event])
        only_onboarding = self._a_session_with_named_events([("onboarding-initialized", {})])
        return both, only_flag, only_onboarding

    def test_two_distinct_event_filters_anded_requires_both_events(self):
        both, _only_flag, _only_onboarding = self._sessions_for_two_distinct_event_filters()

        self._assert_query_matches_session_ids(
            {"operand": "AND", "events": [FLAG_CALLED_WITH_PROPERTIES, ONBOARDING_INITIALIZED]},
            [both],
        )

    def test_two_distinct_event_filters_ored_accepts_either_event(self):
        both, only_flag, only_onboarding = self._sessions_for_two_distinct_event_filters()

        self._assert_query_matches_session_ids(
            {"operand": "OR", "events": [FLAG_CALLED_WITH_PROPERTIES, ONBOARDING_INITIALIZED]},
            [both, only_flag, only_onboarding],
        )

    @parameterized.expand([("and_operand", "AND"), ("or_operand", "OR")])
    def test_duration_control_still_excludes_sessions_matching_event_filters(self, _name: str, operand: str):
        short_session = self._a_session_with_named_events([("onboarding-initialized", {})], duration_seconds=10)
        long_session = self._a_session_with_named_events([("onboarding-initialized", {})], duration_seconds=120)

        self._assert_query_matches_session_ids(
            {
                "operand": operand,
                "events": [ONBOARDING_INITIALIZED],
                "having_predicates": '[{"type":"recording","key":"duration","value":45,"operator":"lt"}]',
            },
            [short_session],
        )

        self._assert_query_matches_session_ids(
            {
                "operand": operand,
                "events": [ONBOARDING_INITIALIZED],
                "having_predicates": '[{"type":"recording","key":"duration","value":45,"operator":"gt"}]',
            },
            [long_session],
        )


@time_machine.travel("2021-01-01T13:46:23", tick=False)
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


@time_machine.travel("2021-01-01T13:46:23", tick=False)
class TestSessionRecordingsExclusionsUnderOrWithPersonsOnEvents(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        sync_execute(TRUNCATE_LOG_ENTRIES_TABLE_SQL)
        self.team.modifiers = {"personsOnEventsMode": PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS.value}
        self.team.save()

    @property
    def an_hour_ago(self):
        return (now() - relativedelta(hours=1)).replace(microsecond=0, second=0)

    def _a_session(self, first_distinct_id: str, events: list[tuple[str, str]]) -> str:
        session_id = str(uuid7())
        produce_replay_summary(
            distinct_id=first_distinct_id,
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        for i, (distinct_id, event_name) in enumerate(events):
            create_event(
                team=self.team,
                distinct_id=distinct_id,
                timestamp=self.an_hour_ago + relativedelta(minutes=i),
                event_name=event_name,
                properties={"$session_id": session_id, "$window_id": "1"},
            )
        return session_id

    @snapshot_clickhouse_queries
    @exclusions_under_or_flag_on()
    def test_negative_person_property_ORed_with_an_event_still_excludes(self, _flag):
        identified_user = "identified-user"
        create_person(team=self.team, distinct_ids=[identified_user], properties={"email": "user@example.com"})

        _identified_after_anonymous_event = self._a_session(
            "anon-1", [("anon-1", "$autocapture"), (identified_user, "$pageview")]
        )
        anonymous_pageview = self._a_session("anon-2", [("anon-2", "$pageview")])
        _anonymous_without_pageview = self._a_session("anon-3", [("anon-3", "$autocapture")])

        assert_query_matches_session_ids(
            team=self.team,
            query={
                "operand": "OR",
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events"}],
                "properties": [{"key": "email", "type": "person", "operator": "is_not_set", "value": "is_not_set"}],
            },
            expected=[anonymous_pageview],
        )

    @snapshot_clickhouse_queries
    @patch("posthog.session_recordings.queries.utils.posthoganalytics.feature_enabled", return_value=True)
    @exclusions_under_or_flag_on()
    def test_negative_cohort_ORed_with_an_event_is_excluded_by_the_blocklist(self, _flag, _anonymous_cohort_fix_flag):
        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True, PERSON_ON_EVENTS_V2_OVERRIDE=True):
            member = "cohort-member"
            non_member = "not-a-cohort-member"
            create_person(team=self.team, distinct_ids=[member], properties={"user_group": "internal"})
            create_person(team=self.team, distinct_ids=[non_member], properties={"user_group": "external"})

            _member_pageview = self._a_session(member, [(member, "$pageview")])
            non_member_pageview = self._a_session(non_member, [(non_member, "$pageview")])
            anonymous_pageview = self._a_session("anon-1", [("anon-1", "$pageview")])

            internal_cohort = Cohort.objects.create(
                team=self.team,
                name="internal_users",
                groups=[{"properties": [{"key": "user_group", "value": "internal", "type": "person"}]}],
            )
            internal_cohort.calculate_people_ch(pending_version=0)

            assert_query_matches_session_ids(
                team=self.team,
                query={
                    "operand": "OR",
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events"}],
                    "properties": [{"key": "id", "value": internal_cohort.pk, "operator": "not_in", "type": "cohort"}],
                },
                expected=[non_member_pageview, anonymous_pageview],
            )
