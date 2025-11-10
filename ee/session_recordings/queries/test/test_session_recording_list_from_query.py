import re
from itertools import product
from uuid import uuid4

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
    _create_event,
    snapshot_clickhouse_queries,
)

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from parameterized import parameterized
from tenacity import retry, stop_after_attempt, wait_exponential

from posthog.schema import PersonsOnEventsMode, RecordingsQuery

from posthog.hogql.ast import SelectQuery
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import prepare_and_print_ast

from posthog.clickhouse.client import sync_execute
from posthog.models import Person
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL

from ee.clickhouse.materialized_columns.columns import get_materialized_columns, materialize


# The HogQL pair of TestClickhouseSessionRecordingsListFromSessionReplay can be renamed when delete the old one
@freeze_time("2021-01-01T13:46:23")
class TestClickhouseSessionRecordingsListFromQuery(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def _print_query(self, query: SelectQuery) -> str:
        return prepare_and_print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
            pretty=True,
        )[0]

    def tearDown(self) -> None:
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())

    @property
    def base_time(self):
        return (now() - relativedelta(hours=1)).replace(microsecond=0, second=0)

    def create_event(
        self,
        distinct_id,
        timestamp,
        team=None,
        event_name="$pageview",
        properties=None,
    ):
        if team is None:
            team = self.team
        if properties is None:
            properties = {"$os": "Windows 95", "$current_url": "aloha.com/2"}
        return _create_event(
            team=team,
            event=event_name,
            timestamp=timestamp,
            distinct_id=distinct_id,
            properties=properties,
        )

    @parameterized.expand(
        [
            [
                "test_poe_v1_still_falls_back_to_person_subquery",
                True,
                False,
                False,
                PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
            ],
            [
                "test_poe_being_unavailable_we_fall_back_to_person_id_overrides",
                False,
                False,
                False,
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
            ],
            [
                "test_poe_being_unavailable_we_fall_back_to_person_subquery_but_still_use_mat_props",
                False,
                False,
                False,
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
            ],
            [
                "test_allow_denormalised_props_fix_does_not_stop_all_poe_processing",
                False,
                True,
                False,
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
            ],
            [
                "test_poe_v2_available_person_properties_are_used_in_replay_listing",
                False,
                True,
                True,
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
            ],
        ]
    )
    def test_effect_of_poe_settings_on_query_generated(
        self,
        _name: str,
        poe_v1: bool,
        poe_v2: bool,
        allow_denormalized_props: bool,
        expected_poe_mode: PersonsOnEventsMode,
    ) -> None:
        with self.settings(
            PERSON_ON_EVENTS_OVERRIDE=poe_v1,
            PERSON_ON_EVENTS_V2_OVERRIDE=poe_v2,
            ALLOW_DENORMALIZED_PROPS_IN_LISTING=allow_denormalized_props,
        ):
            assert self.team.person_on_events_mode == expected_poe_mode
            materialize("events", "rgInternal", table_column="person_properties")

            query = RecordingsQuery.model_validate(
                {
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
            session_recording_list_instance = SessionRecordingListFromQuery(
                query=query, team=self.team, hogql_query_modifiers=None
            )

            hogql_parsed_select = session_recording_list_instance.get_query()
            printed_query = self._print_query(hogql_parsed_select)

            if poe_v1 or poe_v2:
                # Property used directly from event (from materialized column)
                assert "ifNull(equals(nullIf(nullIf(events.mat_pp_rgInternal, ''), 'null')" in printed_query
            else:
                # We get the person property value from the persons JOIN
                assert re.search(
                    r"argMax\(replaceRegexpAll\(nullIf\(nullIf\(JSONExtractRaw\(person\.properties, %\(hogql_val_\d+\)s\), ''\), 'null'\), '^\"|\"\$', ''\), person\.version\) AS properties___rgInternal",
                    printed_query,
                )
                # Then we actually filter on that property value
                assert re.search(
                    r"ifNull\(equals\(events__person\.properties___rgInternal, %\(hogql_val_\d+\)s\), 0\)",
                    printed_query,
                )
            self.assertQueryMatchesSnapshot(printed_query)

    settings_combinations = [
        ["poe v2 and materialized columns allowed", False, True, True],
        ["poe v2 and materialized columns off", False, True, False],
        ["poe off and materialized columns allowed", False, False, True],
        ["poe off and materialized columns not allowed", False, False, False],
        ["poe v1 and materialized columns allowed", True, False, True],
        ["poe v1 and not materialized columns not allowed", True, False, False],
    ]

    # Options for "materialize person columns"
    materialization_options = [
        [" with materialization", True],
        [" without materialization", False],
    ]

    # Expand the parameter list to the product of all combinations with "materialize person columns"
    # e.g. [a, b] x [c, d] = [a, c], [a, d], [b, c], [b, d]
    test_case_combinations = [
        [f"{name}{mat_option}", poe_v1, poe, mat_columns, mat_person]
        for (name, poe_v1, poe, mat_columns), (mat_option, mat_person) in product(
            settings_combinations, materialization_options
        )
    ]

    @parameterized.expand(test_case_combinations)
    @snapshot_clickhouse_queries
    def test_event_filter_with_person_properties_materialized(
        self,
        _name: str,
        poe1_enabled: bool,
        poe2_enabled: bool,
        allow_denormalised_props: bool,
        materialize_person_props: bool,
    ) -> None:
        # KLUDGE: I couldn't figure out how to use @also_test_with_materialized_columns(person_properties=["email"])
        # KLUDGE: and the parameterized.expand decorator at the same time, so we generate test case combos
        # KLUDGE: for materialization on and off to test both sides the way the decorator would have
        if materialize_person_props:
            materialize("events", "email", table_column="person_properties")
            materialize("person", "email")

            @retry(wait=wait_exponential(multiplier=0.5, min=0.5, max=5), stop=stop_after_attempt(10))
            def wait_for_materialized_columns():
                events_col = get_materialized_columns("events").get(("email", "person_properties"))
                person_col = get_materialized_columns("person").get(("email", "properties"))
                if not events_col or not person_col:
                    raise ValueError("Materialized columns not ready yet")
                return events_col, person_col

            wait_for_materialized_columns()

        with self.settings(
            PERSON_ON_EVENTS_OVERRIDE=poe1_enabled,
            PERSON_ON_EVENTS_V2_OVERRIDE=poe2_enabled,
            ALLOW_DENORMALIZED_PROPS_IN_LISTING=allow_denormalised_props,
        ):
            user_one = "test_event_filter_with_person_properties-user"
            user_two = "test_event_filter_with_person_properties-user2"
            session_id_one = f"test_event_filter_with_person_properties-1-{str(uuid4())}"
            session_id_two = f"test_event_filter_with_person_properties-2-{str(uuid4())}"

            Person.objects.create(team=self.team, distinct_ids=[user_one], properties={"email": "bla"})
            Person.objects.create(team=self.team, distinct_ids=[user_two], properties={"email": "bla2"})

            self._add_replay_with_pageview(session_id_one, user_one)
            produce_replay_summary(
                distinct_id=user_one,
                session_id=session_id_one,
                first_timestamp=(self.base_time + relativedelta(seconds=30)),
                team_id=self.team.id,
            )
            self._add_replay_with_pageview(session_id_two, user_two)
            produce_replay_summary(
                distinct_id=user_two,
                session_id=session_id_two,
                first_timestamp=(self.base_time + relativedelta(seconds=30)),
                team_id=self.team.id,
            )

            match_everyone_filter = RecordingsQuery.model_validate(
                {"properties": []},
            )

            session_recording_list_instance = SessionRecordingListFromQuery(
                query=match_everyone_filter, team=self.team, hogql_query_modifiers=None
            )
            (session_recordings, _, _, _) = session_recording_list_instance.run()

            assert sorted([x["session_id"] for x in session_recordings]) == sorted([session_id_one, session_id_two])

            match_bla_filter = RecordingsQuery.model_validate(
                {
                    "properties": [
                        {
                            "key": "email",
                            "value": ["bla"],
                            "operator": "exact",
                            "type": "person",
                        }
                    ]
                },
            )

            session_recording_list_instance = SessionRecordingListFromQuery(
                query=match_bla_filter, team=self.team, hogql_query_modifiers=None
            )
            (session_recordings, _, _, _) = session_recording_list_instance.run()

            assert len(session_recordings) == 1
            assert session_recordings[0]["session_id"] == session_id_one

    def _add_replay_with_pageview(self, session_id: str, user: str) -> None:
        self.create_event(
            user,
            self.base_time,
            properties={"$session_id": session_id, "$window_id": str(uuid4())},
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )

    @parameterized.expand(test_case_combinations)
    @snapshot_clickhouse_queries
    def test_person_id_filter(
        self,
        _name: str,
        poe2_enabled: bool,
        poe1_enabled: bool,
        allow_denormalised_props: bool,
        materialize_person_props: bool,
    ) -> None:
        # KLUDGE: I couldn't figure out how to use @also_test_with_materialized_columns(person_properties=["email"])
        # KLUDGE: and the parameterized.expand decorator at the same time, so we generate test case combos
        # KLUDGE: for materialization on and off to test both sides the way the decorator would have
        if materialize_person_props:
            # it shouldn't matter to this test whether any column is materialized
            # but let's keep the tests in this file similar so we flush out any unexpected interactions
            materialize("events", "email", table_column="person_properties")
            materialize("person", "email")

        with self.settings(
            PERSON_ON_EVENTS_OVERRIDE=poe1_enabled,
            PERSON_ON_EVENTS_V2_OVERRIDE=poe2_enabled,
            ALLOW_DENORMALIZED_PROPS_IN_LISTING=allow_denormalised_props,
        ):
            three_user_ids = ["person-1-distinct-1", "person-1-distinct-2", "person-2"]
            session_id_one = f"test_person_id_filter-session-one"
            session_id_two = f"test_person_id_filter-session-two"
            session_id_three = f"test_person_id_filter-session-three"

            p = Person.objects.create(
                team=self.team,
                distinct_ids=[three_user_ids[0], three_user_ids[1]],
                properties={"email": "bla"},
            )
            Person.objects.create(
                team=self.team,
                distinct_ids=[three_user_ids[2]],
                properties={"email": "bla2"},
            )

            self._add_replay_with_pageview(session_id_one, three_user_ids[0])
            self._add_replay_with_pageview(session_id_two, three_user_ids[1])
            self._add_replay_with_pageview(session_id_three, three_user_ids[2])

            query = RecordingsQuery.model_validate({"person_uuid": str(p.uuid)})
            session_recording_list_instance = SessionRecordingListFromQuery(
                query=query, team=self.team, hogql_query_modifiers=None
            )
            (session_recordings, _, _, _) = session_recording_list_instance.run()
            assert sorted([r["session_id"] for r in session_recordings]) == sorted([session_id_two, session_id_one])

    def test_cursor_based_pagination_single_page(self):
        """Test cursor pagination with results fitting in single page"""
        session_id_one = f"test_cursor_pagination_single_page-1-{uuid4()}"
        session_id_two = f"test_cursor_pagination_single_page-2-{uuid4()}"

        produce_replay_summary(
            session_id=session_id_one,
            team_id=self.team.pk,
            first_timestamp=self.base_time,
            last_timestamp=self.base_time + relativedelta(seconds=30),
        )
        produce_replay_summary(
            session_id=session_id_two,
            team_id=self.team.pk,
            first_timestamp=self.base_time + relativedelta(seconds=10),
            last_timestamp=self.base_time + relativedelta(seconds=40),
        )

        # First page with cursor pagination (no cursor, limit 10)
        query = RecordingsQuery.model_validate({"limit": 10})
        result = SessionRecordingListFromQuery(query=query, team=self.team, hogql_query_modifiers=None).run()

        # Should have all results, no more pages
        self.assertEqual(len(result.results), 2)
        self.assertFalse(result.has_more_recording)
        self.assertIsNone(result.next_cursor)

    def test_cursor_based_pagination_multiple_pages(self):
        """Test cursor pagination across multiple pages"""
        base_session_id = f"test_cursor_pagination_multi_page-{uuid4()}"
        # Create 5 sessions
        for i in range(5):
            produce_replay_summary(
                session_id=f"{base_session_id}-{i}",
                team_id=self.team.pk,
                first_timestamp=self.base_time + relativedelta(seconds=i * 10),
                last_timestamp=self.base_time + relativedelta(seconds=i * 10 + 30),
            )

        # Page 1: Get first 2 items
        query = RecordingsQuery.model_validate({"limit": 2, "order": "start_time", "order_direction": "DESC"})
        result = SessionRecordingListFromQuery(query=query, team=self.team, hogql_query_modifiers=None).run()

        self.assertEqual(len(result.results), 2)
        self.assertTrue(result.has_more_recording)
        self.assertIsNotNone(result.next_cursor)
        page1_ids = [r["session_id"] for r in result.results]

        # Page 2: Use cursor to get next 2 items
        query2 = RecordingsQuery.model_validate(
            {"limit": 2, "order": "start_time", "order_direction": "DESC", "after": result.next_cursor}
        )
        result2 = SessionRecordingListFromQuery(query=query2, team=self.team, hogql_query_modifiers=None).run()

        self.assertEqual(len(result2.results), 2)
        self.assertTrue(result2.has_more_recording)
        self.assertIsNotNone(result2.next_cursor)
        page2_ids = [r["session_id"] for r in result2.results]

        # Page 3: Get last item
        query3 = RecordingsQuery.model_validate(
            {"limit": 2, "order": "start_time", "order_direction": "DESC", "after": result2.next_cursor}
        )
        result3 = SessionRecordingListFromQuery(query=query3, team=self.team, hogql_query_modifiers=None).run()

        self.assertEqual(len(result3.results), 1)
        self.assertFalse(result3.has_more_recording)
        self.assertIsNone(result3.next_cursor)
        page3_ids = [r["session_id"] for r in result3.results]

        # Verify no duplicates across pages
        all_ids = page1_ids + page2_ids + page3_ids
        self.assertEqual(len(all_ids), 5)
        self.assertEqual(len(set(all_ids)), 5)  # All unique

    def test_cursor_pagination_with_different_ordering_fields(self):
        """Test cursor pagination works correctly with console_error_count ordering"""
        base_session_id = f"test_cursor_diff_order-{uuid4()}"

        # Create sessions with different error counts
        produce_replay_summary(
            session_id=f"{base_session_id}-1",
            team_id=self.team.pk,
            console_error_count=5,
            first_timestamp=self.base_time,
            last_timestamp=self.base_time + relativedelta(seconds=30),
        )
        produce_replay_summary(
            session_id=f"{base_session_id}-2",
            team_id=self.team.pk,
            console_error_count=3,
            first_timestamp=self.base_time + relativedelta(seconds=10),
            last_timestamp=self.base_time + relativedelta(seconds=40),
        )
        produce_replay_summary(
            session_id=f"{base_session_id}-3",
            team_id=self.team.pk,
            console_error_count=7,
            first_timestamp=self.base_time + relativedelta(seconds=20),
            last_timestamp=self.base_time + relativedelta(seconds=50),
        )

        # Page 1: Order by console_error_count DESC, get 2 items
        query = RecordingsQuery.model_validate({"limit": 2, "order": "console_error_count", "order_direction": "DESC"})
        result = SessionRecordingListFromQuery(query=query, team=self.team, hogql_query_modifiers=None).run()

        self.assertEqual(len(result.results), 2)
        self.assertTrue(result.has_more_recording)
        # First should have 7 errors, second should have 5
        self.assertEqual(result.results[0]["console_error_count"], 7)
        self.assertEqual(result.results[1]["console_error_count"], 5)

        # Page 2: Use cursor
        query2 = RecordingsQuery.model_validate(
            {"limit": 2, "order": "console_error_count", "order_direction": "DESC", "after": result.next_cursor}
        )
        result2 = SessionRecordingListFromQuery(query=query2, team=self.team, hogql_query_modifiers=None).run()

        self.assertEqual(len(result2.results), 1)
        self.assertFalse(result2.has_more_recording)
        self.assertEqual(result2.results[0]["console_error_count"], 3)

    def test_backward_compatibility_offset_still_works(self):
        """Test that offset-based pagination still works for backward compatibility"""
        base_session_id = f"test_offset_compat-{uuid4()}"

        for i in range(5):
            produce_replay_summary(
                session_id=f"{base_session_id}-{i}",
                team_id=self.team.pk,
                first_timestamp=self.base_time + relativedelta(seconds=i * 10),
                last_timestamp=self.base_time + relativedelta(seconds=i * 10 + 30),
            )

        # Use offset pagination
        query = RecordingsQuery.model_validate({"limit": 2, "offset": 0})
        result = SessionRecordingListFromQuery(query=query, team=self.team, hogql_query_modifiers=None).run()

        self.assertEqual(len(result.results), 2)
        self.assertTrue(result.has_more_recording)
        # Should not have cursor when using offset
        self.assertIsNone(result.next_cursor)

        # Get second page with offset
        query2 = RecordingsQuery.model_validate({"limit": 2, "offset": 2})
        result2 = SessionRecordingListFromQuery(query=query2, team=self.team, hogql_query_modifiers=None).run()

        self.assertEqual(len(result2.results), 2)
        self.assertTrue(result2.has_more_recording)
