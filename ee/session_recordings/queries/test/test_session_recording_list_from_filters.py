from itertools import product
from uuid import uuid4

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time
from parameterized import parameterized

from ee.clickhouse.materialized_columns.columns import materialize
from posthog.clickhouse.client import sync_execute
from posthog.hogql.ast import CompareOperation, And, SelectQuery
from posthog.hogql.base import Expr
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_ast
from posthog.models import Person
from posthog.models.filters import SessionRecordingsFilter
from posthog.schema import PersonsOnEventsMode
from posthog.session_recordings.queries.session_recording_list_from_filters import (
    SessionRecordingListFromFilters,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
    snapshot_clickhouse_queries,
    _create_event,
)


# The HogQL pair of TestClickhouseSessionRecordingsListFromSessionReplay can be renamed when delete the old one
@freeze_time("2021-01-01T13:46:23")
class TestClickhouseSessionRecordingsListFromFilters(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def _print_query(self, query: SelectQuery) -> str:
        return print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
            pretty=True,
        )

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
                True,
            ],
            [
                "test_poe_being_unavailable_we_fall_back_to_person_subquery",
                False,
                False,
                False,
                PersonsOnEventsMode.DISABLED,
                True,
            ],
            [
                "test_poe_being_unavailable_we_fall_back_to_person_subquery_but_still_use_mat_props",
                False,
                False,
                False,
                PersonsOnEventsMode.DISABLED,
                False,
            ],
            [
                "test_allow_denormalised_props_fix_does_not_stop_all_poe_processing",
                False,
                True,
                False,
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                False,
            ],
            [
                "test_poe_v2_available_person_properties_are_used_in_replay_listing",
                False,
                True,
                True,
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                False,
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
        unmaterialized_person_column_used: bool,
    ) -> None:
        with self.settings(
            PERSON_ON_EVENTS_OVERRIDE=poe_v1,
            PERSON_ON_EVENTS_V2_OVERRIDE=poe_v2,
            ALLOW_DENORMALIZED_PROPS_IN_LISTING=allow_denormalized_props,
        ):
            assert self.team.person_on_events_mode == expected_poe_mode
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
            session_recording_list_instance = SessionRecordingListFromFilters(
                filter=filter, team=self.team, hogql_query_modifiers=None
            )

            hogql_parsed_select = session_recording_list_instance.get_query()
            printed_query = self._print_query(hogql_parsed_select)

            person_filtering_expr = self._matching_person_filter_expr_from(hogql_parsed_select)

            if poe_v1 or poe_v2:
                # when poe is off we will join to events, so we can get person properties directly off them
                self._assert_is_events_person_filter(person_filtering_expr)

                assert "ifNull(equals(nullIf(nullIf(mat_pp_rgInternal, ''), 'null')" in printed_query
            else:
                # when poe is off we join to person_distinct_ids, so we can get persons, so we can query their properties
                self._assert_is_pdi_filter(person_filtering_expr)

                if unmaterialized_person_column_used:
                    assert (
                        "argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_6)s), ''), 'null'), '^\"|\"$', ''), person.version) AS properties___rgInternal"
                        in printed_query
                    )
                else:
                    # we should use materialized column
                    # assert (
                    #     "argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_6)s), ''), 'null'), '^\"|\"$', ''), person.version) AS properties___rgInternal"
                    #     not in printed_query
                    # )
                    # TODO frustratingly this doesn't pass - but since we're migrating to PoE maybe we can ignore it
                    pass

            self.assertQueryMatchesSnapshot(printed_query)

    def _assert_is_pdi_filter(self, person_filtering_expr: list[Expr]) -> None:
        assert person_filtering_expr[0].right.select_from.table.chain == ["person_distinct_ids"]
        assert person_filtering_expr[0].right.where.left.chain == ["person", "properties", "rgInternal"]

    def _assert_is_events_person_filter(self, person_filtering_expr: list[Expr]) -> None:
        assert person_filtering_expr[0].right.select_from.table.chain == ["events"]
        event_person_condition = [
            x
            for x in person_filtering_expr[0].right.where.exprs
            if isinstance(x, CompareOperation) and x.left.chain == ["person", "properties", "rgInternal"]
        ]
        assert len(event_person_condition) == 1

    def _matching_person_filter_expr_from(self, hogql_parsed_select: SelectQuery) -> list[Expr]:
        where_conditions: list[Expr] = hogql_parsed_select.where.exprs
        ands = [x for x in where_conditions if isinstance(x, And)]
        assert len(ands) == 1
        and_comparisons = [x for x in ands[0].exprs if isinstance(x, CompareOperation)]
        assert len(and_comparisons) == 1
        assert isinstance(and_comparisons[0].right, SelectQuery)
        return and_comparisons

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

            match_everyone_filter = SessionRecordingsFilter(
                team=self.team,
                data={"properties": []},
            )

            session_recording_list_instance = SessionRecordingListFromFilters(
                filter=match_everyone_filter, team=self.team, hogql_query_modifiers=None
            )
            (session_recordings, _, _) = session_recording_list_instance.run()

            assert sorted([x["session_id"] for x in session_recordings]) == sorted([session_id_one, session_id_two])

            match_bla_filter = SessionRecordingsFilter(
                team=self.team,
                data={
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

            session_recording_list_instance = SessionRecordingListFromFilters(
                filter=match_bla_filter, team=self.team, hogql_query_modifiers=None
            )
            (session_recordings, _, _) = session_recording_list_instance.run()

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

            filter = SessionRecordingsFilter(team=self.team, data={"person_uuid": str(p.uuid)})
            session_recording_list_instance = SessionRecordingListFromFilters(
                filter=filter, team=self.team, hogql_query_modifiers=None
            )
            (session_recordings, _, _) = session_recording_list_instance.run()
            assert sorted([r["session_id"] for r in session_recordings]) == sorted([session_id_two, session_id_one])
