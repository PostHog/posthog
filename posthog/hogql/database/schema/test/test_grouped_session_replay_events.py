from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.models.team import Team
from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL


def _grouped_table_registered() -> bool:
    from posthog.hogql.database.database import ROOT_TABLES__DO_NOT_ADD_ANY_MORE

    return "grouped_session_replay_events" in ROOT_TABLES__DO_NOT_ADD_ANY_MORE


pytestmark = pytest.mark.skipif(
    not _grouped_table_registered(),
    reason=(
        "grouped_session_replay_events is not yet registered in HogQL. "
        "See products/replay/SESSION_REPLAY_HOGQL_PLAN.md PR 2 — tests auto-enable once registered."
    ),
)


BASE_TIME = datetime(2024, 7, 1, 10, 0, 0, tzinfo=UTC)

PARTS = 3
PER_PART_CLICKS = 1
PER_PART_KEYPRESSES = 2
PER_PART_MOUSE = 3
PER_PART_ACTIVE_MS = 500
PER_PART_CONSOLE_LOG = 1
PER_PART_CONSOLE_WARN = 1
PER_PART_CONSOLE_ERROR = 1
PER_PART_SIZE = 50
PER_PART_EVENT_COUNT = 17
PER_PART_MESSAGE_COUNT = 11

OTHER_TEAM_PER_PART_CLICKS = 100


@freeze_time("2024-07-01T12:00:00")
class TestGroupedSessionReplayEventsContract(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        self.other_team = Team.objects.create(organization=self.organization, name="grouped-replay-test-other-team")
        self.single_part_session = self._given_single_part_session()
        self.many_parts_session = self._given_many_parts_session()
        self.varied_snapshot_session = self._given_session_with_varied_snapshot_sources()
        self.varied_retention_session = self._given_session_with_varied_retention_periods()
        self.mixed_deleted_session = self._given_session_with_mixed_deleted_parts()
        self.identified_mid_session = self._given_session_that_identifies_mid_way()
        self.repeated_url_session = self._given_session_with_repeated_urls()
        self.ai_tags_session = self._given_session_with_varied_ai_tags()
        self.joined_session = self._given_session_with_analytics_event()
        self.cross_team_session = self._given_same_session_id_across_two_teams()

    def _given_single_part_session(self) -> str:
        session_id = str(uuid7())
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="d_single",
            session_id=session_id,
            first_timestamp=BASE_TIME,
            last_timestamp=BASE_TIME + timedelta(minutes=5),
            click_count=3,
            first_url="https://a.example",
            all_urls=["https://a.example"],
            snapshot_source="web",
            snapshot_library="posthog-js",
            retention_period_days=30,
            ensure_analytics_event_in_session=False,
        )
        return session_id

    def _given_many_parts_session(self) -> str:
        session_id = str(uuid7())
        for i in range(PARTS):
            produce_replay_summary(
                team_id=self.team.pk,
                distinct_id="d_many",
                session_id=session_id,
                first_timestamp=BASE_TIME + timedelta(minutes=i * 10),
                last_timestamp=BASE_TIME + timedelta(minutes=i * 10 + 5),
                click_count=PER_PART_CLICKS,
                keypress_count=PER_PART_KEYPRESSES,
                mouse_activity_count=PER_PART_MOUSE,
                active_milliseconds=PER_PART_ACTIVE_MS,
                console_log_count=PER_PART_CONSOLE_LOG,
                console_warn_count=PER_PART_CONSOLE_WARN,
                console_error_count=PER_PART_CONSOLE_ERROR,
                size=PER_PART_SIZE,
                event_count=PER_PART_EVENT_COUNT,
                message_count=PER_PART_MESSAGE_COUNT,
                first_url=f"https://part-{i}.example",
                all_urls=[f"https://part-{i}.example"],
                snapshot_source="web",
                snapshot_library="posthog-js",
                retention_period_days=30,
                ensure_analytics_event_in_session=False,
            )
        return session_id

    def _given_session_with_varied_snapshot_sources(self) -> str:
        session_id = str(uuid7())
        for i, (source, library) in enumerate(
            [("web", "posthog-js"), ("mobile", "posthog-ios"), ("mobile", "posthog-android")]
        ):
            produce_replay_summary(
                team_id=self.team.pk,
                distinct_id="d_varied_snap",
                session_id=session_id,
                first_timestamp=BASE_TIME + timedelta(minutes=i),
                last_timestamp=BASE_TIME + timedelta(minutes=i + 1),
                snapshot_source=source,
                snapshot_library=library,
                retention_period_days=30,
                ensure_analytics_event_in_session=False,
            )
        return session_id

    def _given_session_with_varied_retention_periods(self) -> str:
        session_id = str(uuid7())
        for i, retention in enumerate([7, 30, 90]):
            produce_replay_summary(
                team_id=self.team.pk,
                distinct_id="d_varied_ret",
                session_id=session_id,
                first_timestamp=BASE_TIME + timedelta(minutes=i),
                last_timestamp=BASE_TIME + timedelta(minutes=i + 1),
                retention_period_days=retention,
                ensure_analytics_event_in_session=False,
            )
        return session_id

    def _given_session_with_mixed_deleted_parts(self) -> str:
        session_id = str(uuid7())
        for is_deleted in (False, False, True):
            produce_replay_summary(
                team_id=self.team.pk,
                distinct_id="d_del",
                session_id=session_id,
                first_timestamp=BASE_TIME,
                last_timestamp=BASE_TIME + timedelta(minutes=1),
                is_deleted=is_deleted,
                ensure_analytics_event_in_session=False,
            )
        return session_id

    def _given_session_that_identifies_mid_way(self) -> str:
        session_id = str(uuid7())
        for i, distinct_id in enumerate(["anon_visitor", "anon_visitor", "identified_user"]):
            produce_replay_summary(
                team_id=self.team.pk,
                distinct_id=distinct_id,
                session_id=session_id,
                first_timestamp=BASE_TIME + timedelta(minutes=i * 5),
                last_timestamp=BASE_TIME + timedelta(minutes=i * 5 + 3),
                ensure_analytics_event_in_session=False,
            )
        return session_id

    def _given_session_with_repeated_urls(self) -> str:
        session_id = str(uuid7())
        for i in range(PARTS):
            produce_replay_summary(
                team_id=self.team.pk,
                distinct_id="d_dup",
                session_id=session_id,
                first_timestamp=BASE_TIME + timedelta(minutes=i),
                last_timestamp=BASE_TIME + timedelta(minutes=i + 1),
                first_url="https://dup.example",
                all_urls=["https://dup.example"],
                ensure_analytics_event_in_session=False,
            )
        return session_id

    def _given_session_with_varied_ai_tags(self) -> str:
        session_id = str(uuid7())
        for i, (fixed, freeform, highlighted) in enumerate(
            [
                (["rage_click"], ["confused"], False),
                (["rage_click", "dead_click"], ["angry"], True),
                (["dead_click"], ["frustrated"], False),
            ]
        ):
            produce_replay_summary(
                team_id=self.team.pk,
                distinct_id="d_ai",
                session_id=session_id,
                first_timestamp=BASE_TIME + timedelta(minutes=i),
                last_timestamp=BASE_TIME + timedelta(minutes=i + 1),
                ai_tags_fixed=fixed,
                ai_tags_freeform=freeform,
                ai_highlighted=highlighted,
                ensure_analytics_event_in_session=False,
            )
        return session_id

    def _given_session_with_analytics_event(self) -> str:
        session_id = str(uuid7())
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="d_joined",
            session_id=session_id,
            first_timestamp=BASE_TIME,
            last_timestamp=BASE_TIME + timedelta(minutes=1),
            ensure_analytics_event_in_session=False,
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d_joined",
            properties={"$session_id": session_id, "$current_url": "https://joined.example"},
        )
        flush_persons_and_events()
        return session_id

    def _given_same_session_id_across_two_teams(self) -> str:
        session_id = str(uuid7())
        for i in range(PARTS):
            produce_replay_summary(
                team_id=self.team.pk,
                distinct_id="d_cross_mine",
                session_id=session_id,
                first_timestamp=BASE_TIME + timedelta(minutes=i),
                last_timestamp=BASE_TIME + timedelta(minutes=i + 1),
                click_count=PER_PART_CLICKS,
                ensure_analytics_event_in_session=False,
            )
            produce_replay_summary(
                team_id=self.other_team.pk,
                distinct_id="d_cross_other",
                session_id=session_id,
                first_timestamp=BASE_TIME + timedelta(minutes=i),
                last_timestamp=BASE_TIME + timedelta(minutes=i + 1),
                click_count=OTHER_TEAM_PER_PART_CLICKS,
                ensure_analytics_event_in_session=False,
            )
        return session_id

    def _session_row(self, session_id: str, team: Team | None = None) -> dict:
        response = execute_hogql_query(
            parse_select(
                "select * from grouped_session_replay_events where session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
            team or self.team,
        )
        assert response.results, f"expected exactly one row for session {session_id}, got none"
        return dict(zip(response.columns or [], response.results[0]))

    def _row_count_for(self, session_id: str, team: Team | None = None) -> int:
        response = execute_hogql_query(
            parse_select(
                "select count() from grouped_session_replay_events where session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
            team or self.team,
        )
        return response.results[0][0]

    @parameterized.expand(
        [
            "single_part_session",
            "many_parts_session",
            "varied_snapshot_session",
            "varied_retention_session",
            "mixed_deleted_session",
            "identified_mid_session",
            "repeated_url_session",
            "ai_tags_session",
        ]
    )
    def test_session_collapses_to_exactly_one_row(self, session_attr: str):
        assert self._row_count_for(getattr(self, session_attr)) == 1

    @parameterized.expand(
        [
            ("click_count", PARTS * PER_PART_CLICKS),
            ("keypress_count", PARTS * PER_PART_KEYPRESSES),
            ("mouse_activity_count", PARTS * PER_PART_MOUSE),
            ("active_milliseconds", PARTS * PER_PART_ACTIVE_MS),
            ("console_log_count", PARTS * PER_PART_CONSOLE_LOG),
            ("console_warn_count", PARTS * PER_PART_CONSOLE_WARN),
            ("console_error_count", PARTS * PER_PART_CONSOLE_ERROR),
            ("size", PARTS * PER_PART_SIZE),
            ("event_count", PARTS * PER_PART_EVENT_COUNT),
            ("message_count", PARTS * PER_PART_MESSAGE_COUNT),
        ]
    )
    def test_counter_sums_across_state_parts(self, field: str, expected: int):
        assert self._session_row(self.many_parts_session)[field] == expected

    def test_start_time_is_earliest_first_timestamp(self):
        assert self._session_row(self.many_parts_session)["start_time"] == BASE_TIME

    def test_end_time_is_latest_last_timestamp(self):
        assert self._session_row(self.many_parts_session)["end_time"] == BASE_TIME + timedelta(minutes=25)

    def test_first_url_returns_earliest_url_as_string(self):
        assert self._session_row(self.many_parts_session)["first_url"] == "https://part-0.example"

    def test_all_urls_is_union_of_distinct_urls_across_state_parts(self):
        assert sorted(self._session_row(self.many_parts_session)["all_urls"]) == [
            "https://part-0.example",
            "https://part-1.example",
            "https://part-2.example",
        ]

    def test_all_urls_dedupes_repeated_url_across_state_parts(self):
        assert self._session_row(self.repeated_url_session)["all_urls"] == ["https://dup.example"]

    def test_snapshot_source_returns_earliest_value_as_string(self):
        assert self._session_row(self.varied_snapshot_session)["snapshot_source"] == "web"

    def test_snapshot_library_returns_earliest_value_as_string(self):
        assert self._session_row(self.varied_snapshot_session)["snapshot_library"] == "posthog-js"

    def test_retention_period_days_is_max_across_state_parts(self):
        assert self._session_row(self.varied_retention_session)["retention_period_days"] == 90

    def test_is_deleted_is_truthy_if_any_state_part_is_deleted(self):
        assert self._session_row(self.mixed_deleted_session)["is_deleted"] in (1, True)

    def test_distinct_id_is_best_effort_latest_while_parts_unmerged(self):
        # Best-effort: see GroupedSessionReplayEventsTable docstring.
        assert self._session_row(self.identified_mid_session)["distinct_id"] in {"anon_visitor", "identified_user"}

    def test_distinct_id_is_stable_when_every_state_part_agrees(self):
        assert self._session_row(self.many_parts_session)["distinct_id"] == "d_many"

    def test_ai_tags_fixed_unions_across_state_parts(self):
        assert sorted(self._session_row(self.ai_tags_session)["ai_tags_fixed"]) == ["dead_click", "rage_click"]

    def test_ai_tags_freeform_unions_across_state_parts(self):
        assert sorted(self._session_row(self.ai_tags_session)["ai_tags_freeform"]) == [
            "angry",
            "confused",
            "frustrated",
        ]

    def test_ai_highlighted_is_truthy_if_any_state_part_is_highlighted(self):
        assert self._session_row(self.ai_tags_session)["ai_highlighted"] in (1, True)

    def test_select_star_returns_one_row_with_expected_columns_and_readable_values(self):
        response = execute_hogql_query(
            parse_select(
                "select * from grouped_session_replay_events where session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=self.single_part_session)},
            ),
            self.team,
        )
        assert len(response.results) == 1
        assert response.columns is not None
        for expected_column in (
            "session_id",
            "distinct_id",
            "start_time",
            "end_time",
            "click_count",
            "first_url",
            "all_urls",
            "is_deleted",
        ):
            assert expected_column in response.columns, f"{expected_column!r} missing from select *"
        assert "team_id" not in response.columns, "team_id is auto-excluded from SELECT * by HogQL convention"

        row = dict(zip(response.columns, response.results[0]))
        assert row["first_url"] == "https://a.example"
        assert row["snapshot_source"] == "web"
        assert row["snapshot_library"] == "posthog-js"

    def test_events_lazy_join_resolves_through_grouped_view(self):
        response = execute_hogql_query(
            parse_select(
                "select distinct events.event from grouped_session_replay_events where session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=self.joined_session)},
            ),
            self.team,
        )
        assert response.results == [("$pageview",)]

    def test_session_lazy_join_resolves_through_grouped_view(self):
        response = execute_hogql_query(
            parse_select(
                "select session.session_id from grouped_session_replay_events where session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=self.joined_session)},
            ),
            self.team,
        )
        assert len(response.results) == 1

    def test_is_deleted_is_zero_when_no_state_part_is_deleted(self):
        assert self._session_row(self.single_part_session)["is_deleted"] in (0, False)

    def test_ai_highlighted_is_zero_when_no_state_part_is_highlighted(self):
        assert self._session_row(self.single_part_session)["ai_highlighted"] in (0, False)

    def test_cross_team_writes_with_same_session_id_do_not_pollute_current_team_row(self):
        row_as_my_team = self._session_row(self.cross_team_session)
        assert row_as_my_team["click_count"] == PARTS * PER_PART_CLICKS
        assert row_as_my_team["distinct_id"] == "d_cross_mine"

        row_as_other_team = self._session_row(self.cross_team_session, team=self.other_team)
        assert row_as_other_team["click_count"] == PARTS * OTHER_TEAM_PER_PART_CLICKS
        assert row_as_other_team["distinct_id"] == "d_cross_other"

    def test_count_works_when_no_table_fields_are_projected(self):
        # HogQL injects `SELECT 1` into the inner subquery when requested_fields is
        # empty, so `SELECT count()` does not hit the "no aggregation defined" branch
        # of the lazy_select resolver.
        response = execute_hogql_query(
            parse_select("select count() from grouped_session_replay_events"),
            self.team,
        )
        assert response.results and response.results[0][0] > 0

    def test_other_teams_session_is_invisible_to_current_team(self):
        other_only_session = str(uuid7())
        produce_replay_summary(
            team_id=self.other_team.pk,
            distinct_id="d_other_only",
            session_id=other_only_session,
            first_timestamp=BASE_TIME,
            last_timestamp=BASE_TIME + timedelta(minutes=1),
            ensure_analytics_event_in_session=False,
        )
        assert self._row_count_for(other_only_session) == 0
