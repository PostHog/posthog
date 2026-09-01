from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, create_person_id_override_by_distinct_id
from unittest.mock import patch

from django.test import override_settings
from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from parameterized import parameterized

from posthog.schema import PersonPropertyFilter, PersonsOnEventsMode, PropertyOperator, RecordingsQuery

from posthog.hogql import ast

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.log_entries import TRUNCATE_LOG_ENTRIES_TABLE_SQL
from posthog.session_recordings.queries.sub_queries.events_subquery import ReplayFiltersEventsSubQuery
from posthog.session_recordings.queries.test.listing_recordings.test_utils import (
    assert_query_matches_session_ids,
    create_event,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL
from posthog.test.persons import create_person


@freeze_time("2021-01-01T13:46:23")
@override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=True)
class TestPersonPropertyHybridQuery(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        sync_execute(TRUNCATE_LOG_ENTRIES_TABLE_SQL)

    def _assert_query_matches_session_ids(
        self, query: dict | None, expected: list[str], sort_results_when_asserting: bool = True
    ) -> None:
        assert_query_matches_session_ids(
            team=self.team, query=query, expected=expected, sort_results_when_asserting=sort_results_when_asserting
        )

    @property
    def an_hour_ago(self):
        return (now() - relativedelta(hours=1)).replace(microsecond=0, second=0)

    def _subquery_for_mode(self, mode: PersonsOnEventsMode) -> ReplayFiltersEventsSubQuery:
        self.team.modifiers = {"personsOnEventsMode": mode.value}
        return ReplayFiltersEventsSubQuery(team=self.team, query=RecordingsQuery())

    @parameterized.expand(
        [
            (PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,),
            (PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,),
            (PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,),
            (PersonsOnEventsMode.DISABLED,),
        ]
    )
    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_hybrid_query_stays_off_in_every_mode_while_the_flag_is_off(
        self, mode: PersonsOnEventsMode, mock_feature_enabled
    ) -> None:
        assert self._subquery_for_mode(mode)._is_hybrid_query_mode_enabled() is False

    @parameterized.expand(
        [
            (PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS, "person_id"),
            (PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED, "person_id"),
            (PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS, "distinct_id"),
            (PersonsOnEventsMode.DISABLED, "distinct_id"),
        ]
    )
    def test_hybrid_query_matches_on_person_id_only_when_overrides_apply(
        self, mode: PersonsOnEventsMode, expected_column: str
    ) -> None:
        subquery = self._subquery_for_mode(mode)

        query = subquery._get_person_id_based_sessions_query(
            [
                PersonPropertyFilter(
                    key="email",
                    value="user@example.com",
                    operator=PropertyOperator.EXACT,
                    type="person",
                )
            ]
        )

        assert isinstance(query.where, ast.And)
        matched = {
            expr.left.chain[-1]
            for expr in query.where.exprs
            if isinstance(expr, ast.CompareOperation) and isinstance(expr.left, ast.Field)
        }
        unusable_column = "distinct_id" if expected_column == "person_id" else "person_id"
        assert expected_column in matched
        assert unusable_column not in matched

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_hybrid_query_finds_pre_identification_sessions(self, mock_feature_enabled) -> None:
        with freeze_time("2021-08-21T20:00:00.000Z"):
            anonymous_id = "anonymous_user_456"
            identified_id = "identified_user_456"
            session_id_before = "session_before_identification_456"
            session_id_after = "session_after_identification_456"

            produce_replay_summary(
                distinct_id=anonymous_id,
                session_id=session_id_before,
                first_timestamp=self.an_hour_ago - relativedelta(minutes=10),
                team_id=self.team.id,
            )
            create_event(
                anonymous_id,
                self.an_hour_ago - relativedelta(minutes=10),
                team=self.team,
                event_name="$pageview",
                properties={"$session_id": session_id_before},
            )

            create_person(
                team=self.team,
                distinct_ids=[anonymous_id, identified_id],
                properties={"email": "user@example.com"},
            )

            produce_replay_summary(
                distinct_id=identified_id,
                session_id=session_id_after,
                first_timestamp=self.an_hour_ago,
                team_id=self.team.id,
            )
            create_event(
                identified_id,
                self.an_hour_ago,
                team=self.team,
                event_name="$pageview",
                properties={"$session_id": session_id_after},
            )

            # Carries no $session_id, so it reads as NULL. It must not reach the session id
            # set the replay table is matched against, which rejects a NULL.
            create_event(identified_id, self.an_hour_ago, team=self.team)

            # The merge itself. The anonymous event was written before the person existed, so it
            # still carries a pre-merge person_id, and only this override row ties it to the
            # person the identify produced. That is the shape a real merge leaves behind, and it
            # is what makes events.person_id resolve to the merged person in an override mode.
            create_person_id_override_by_distinct_id(anonymous_id, identified_id, self.team.pk)

            self._assert_query_matches_session_ids(
                {
                    "properties": [
                        {
                            "key": "email",
                            "value": "user@example.com",
                            "type": "person",
                            "operator": "exact",
                        }
                    ]
                },
                [session_id_before, session_id_after],
            )

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_hybrid_query_finds_all_person_sessions(self, mock_feature_enabled) -> None:
        with freeze_time("2021-08-21T20:00:00.000Z"):
            distinct_id_1 = "distinct_1"
            distinct_id_2 = "distinct_2"
            distinct_id_3 = "distinct_3"
            session_id_1 = "session_1"
            session_id_2 = "session_2"
            session_id_3 = "session_3"

            create_person(
                team=self.team,
                distinct_ids=[distinct_id_1, distinct_id_2, distinct_id_3],
                properties={"email": "multi@example.com"},
            )

            produce_replay_summary(
                distinct_id=distinct_id_1,
                session_id=session_id_1,
                first_timestamp=self.an_hour_ago,
                team_id=self.team.id,
            )
            create_event(
                distinct_id_1,
                self.an_hour_ago,
                team=self.team,
                event_name="$pageview",
                properties={"$session_id": session_id_1},
            )

            produce_replay_summary(
                distinct_id=distinct_id_2,
                session_id=session_id_2,
                first_timestamp=self.an_hour_ago + relativedelta(minutes=10),
                team_id=self.team.id,
            )
            create_event(
                distinct_id_2,
                self.an_hour_ago + relativedelta(minutes=10),
                team=self.team,
                event_name="$pageview",
                properties={"$session_id": session_id_2},
            )

            produce_replay_summary(
                distinct_id=distinct_id_3,
                session_id=session_id_3,
                first_timestamp=self.an_hour_ago + relativedelta(minutes=20),
                team_id=self.team.id,
            )
            create_event(
                distinct_id_3,
                self.an_hour_ago + relativedelta(minutes=20),
                team=self.team,
                event_name="$pageview",
                properties={"$session_id": session_id_3},
            )

            self._assert_query_matches_session_ids(
                {
                    "properties": [
                        {
                            "key": "email",
                            "value": "multi@example.com",
                            "type": "person",
                            "operator": "exact",
                        }
                    ]
                },
                [session_id_1, session_id_2, session_id_3],
            )

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_hybrid_query_skips_negative_operators(self, mock_feature_enabled) -> None:
        """
        Test that _should_use_hybrid_query returns False when person property filters
        have negative operators, even when the feature flag is enabled.
        """
        # Test with IS_NOT operator
        query_with_is_not = RecordingsQuery(
            properties=[
                PersonPropertyFilter(
                    key="email",
                    value="internal@company.com",
                    operator=PropertyOperator.IS_NOT,
                    type="person",
                )
            ]
        )
        subquery = ReplayFiltersEventsSubQuery(team=self.team, query=query_with_is_not)
        person_props = subquery.person_properties
        assert person_props is not None
        self.assertFalse(
            subquery._should_use_hybrid_query(person_props),
            "Hybrid query should NOT be used with IS_NOT operator",
        )

        # Test with NOT_ICONTAINS operator
        query_with_not_icontains = RecordingsQuery(
            properties=[
                PersonPropertyFilter(
                    key="email",
                    value="company.com",
                    operator=PropertyOperator.NOT_ICONTAINS,
                    type="person",
                )
            ]
        )
        subquery = ReplayFiltersEventsSubQuery(team=self.team, query=query_with_not_icontains)
        person_props = subquery.person_properties
        assert person_props is not None
        self.assertFalse(
            subquery._should_use_hybrid_query(person_props),
            "Hybrid query should NOT be used with NOT_ICONTAINS operator",
        )

        # Test with NOT_REGEX operator
        query_with_not_regex = RecordingsQuery(
            properties=[
                PersonPropertyFilter(
                    key="email",
                    value=".*@internal\\.com",
                    operator=PropertyOperator.NOT_REGEX,
                    type="person",
                )
            ]
        )
        subquery = ReplayFiltersEventsSubQuery(team=self.team, query=query_with_not_regex)
        person_props = subquery.person_properties
        assert person_props is not None
        self.assertFalse(
            subquery._should_use_hybrid_query(person_props),
            "Hybrid query should NOT be used with NOT_REGEX operator",
        )

        # Test with IS_NOT_SET operator
        query_with_is_not_set = RecordingsQuery(
            properties=[
                PersonPropertyFilter(
                    key="email",
                    operator=PropertyOperator.IS_NOT_SET,
                    type="person",
                )
            ]
        )
        subquery = ReplayFiltersEventsSubQuery(team=self.team, query=query_with_is_not_set)
        person_props = subquery.person_properties
        assert person_props is not None
        self.assertFalse(
            subquery._should_use_hybrid_query(person_props),
            "Hybrid query should NOT be used with IS_NOT_SET operator",
        )

        # Test that positive operators still work
        query_with_exact = RecordingsQuery(
            properties=[
                PersonPropertyFilter(
                    key="email",
                    value="user@example.com",
                    operator=PropertyOperator.EXACT,
                    type="person",
                )
            ]
        )
        subquery = ReplayFiltersEventsSubQuery(team=self.team, query=query_with_exact)
        person_props = subquery.person_properties
        assert person_props is not None
        self.assertTrue(
            subquery._should_use_hybrid_query(person_props),
            "Hybrid query SHOULD be used with EXACT operator",
        )
