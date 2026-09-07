from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.hog_invocation_results.sql import INSERT_HOG_INVOCATION_RESULT_SQL

from products.cdp.backend.services.stuck_invocations import (
    STUCK_INVOCATION_ERROR_KIND,
    StuckInvocation,
    StuckInvocationScope,
    build_terminal_row,
    unstick_invocations,
)

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
TEAM_ID = 1
FUNCTION_ID = "018f0000-0000-0000-0000-00000000f00d"
INVOCATION_ID = "018f0000-0000-0000-0000-0000000000a1"


def _insert_row(
    *,
    team_id: int,
    invocation_id: str,
    status: str,
    version: int,
    scheduled_at: datetime,
    is_deleted: int = 0,
    invocation_globals: str = "{}",
    started_at: Optional[datetime] = None,
) -> None:
    params: dict[str, Any] = {
        "team_id": team_id,
        "function_kind": "hog_function",
        "function_id": FUNCTION_ID,
        "invocation_id": invocation_id,
        "parent_run_id": "",
        "status": status,
        "attempts": 0,
        "is_retry": 0,
        "scheduled_at": scheduled_at,
        "first_scheduled_at": scheduled_at,
        "started_at": started_at,
        "finished_at": None,
        "duration_ms": None,
        "error_kind": "",
        "error_message": "",
        "event_uuid": "",
        "distinct_id": "user-1",
        "person_id": "person-1",
        "invocation_globals": invocation_globals,
        "version": version,
        "is_deleted": is_deleted,
    }
    sync_execute(INSERT_HOG_INVOCATION_RESULT_SQL, params)


def _scope(
    team_id: int,
    *,
    min_age_hours: int = 24,
    function_id: Optional[str] = None,
    invocation_ids: tuple[str, ...] = (),
) -> StuckInvocationScope:
    return StuckInvocationScope(
        team_id=team_id,
        function_kind="hog_function",
        function_id=function_id,
        invocation_ids=invocation_ids,
        min_age=timedelta(hours=min_age_hours),
        limit=100,
    )


class TestStuckInvocations(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            # A run whose terminal row was never produced, old enough to be
            # certain no worker is still holding it.
            ("only_running", "01", [("running", 1, -48)], True),
            ("running_then_succeeded", "02", [("running", 1, -48), ("succeeded", 2, -48)], False),
            # The terminal row carries the retry's scheduled_at, which is inside
            # the age cutoff while the running row sits outside it. Filtering
            # rows by scheduled_at instead of the aggregate would hide the
            # terminal row here and report a finished run as stuck.
            ("terminal_row_scheduled_after_cutoff", "03", [("running", 1, -48), ("succeeded", 2, -1)], False),
            ("running_but_too_recent", "04", [("running", 1, -2)], False),
            # A lower version does not win the argMax, so the run still reads
            # as running and is still stuck. This is the re-run case that
            # produced the stuck rows in the first place.
            ("terminal_row_superseded_by_running", "05", [("succeeded", 1, -48), ("running", 2, -48)], True),
        ]
    )
    def test_selects_only_invocations_left_on_running(
        self, _name: str, suffix: str, rows: list[tuple[str, int, int]], expected_stuck: bool
    ) -> None:
        invocation_id = f"{INVOCATION_ID[:-2]}{suffix}"
        for status, version, hours_ago in rows:
            _insert_row(
                team_id=self.team.pk,
                invocation_id=invocation_id,
                status=status,
                version=version,
                scheduled_at=NOW + timedelta(hours=hours_ago),
            )

        with patch("products.cdp.backend.services.stuck_invocations.producer_scope"):
            stuck = unstick_invocations(_scope(self.team.pk), now=NOW, dry_run=False)

        assert [invocation.invocation_id for invocation in stuck] == ([invocation_id] if expected_stuck else [])

    def test_deleted_invocations_are_left_alone(self) -> None:
        _insert_row(
            team_id=self.team.pk,
            invocation_id=INVOCATION_ID,
            status="running",
            version=1,
            scheduled_at=NOW - timedelta(hours=48),
        )
        _insert_row(
            team_id=self.team.pk,
            invocation_id=INVOCATION_ID,
            status="running",
            version=2,
            scheduled_at=NOW - timedelta(hours=48),
            is_deleted=1,
        )

        with patch("products.cdp.backend.services.stuck_invocations.producer_scope"):
            stuck = unstick_invocations(_scope(self.team.pk), now=NOW, dry_run=False)

        assert stuck == []

    def test_invocation_id_filter_leaves_the_other_stuck_runs_alone(self) -> None:
        # Unsticking one reported run is the common case, and the filter is the
        # only thing standing between that and marking every stuck run in the
        # team failed.
        other_invocation_id = f"{INVOCATION_ID[:-2]}99"
        for invocation_id in (INVOCATION_ID, other_invocation_id):
            _insert_row(
                team_id=self.team.pk,
                invocation_id=invocation_id,
                status="running",
                version=1,
                scheduled_at=NOW - timedelta(hours=48),
            )

        with patch("products.cdp.backend.services.stuck_invocations.producer_scope"):
            stuck = unstick_invocations(
                _scope(self.team.pk, function_id=FUNCTION_ID, invocation_ids=(INVOCATION_ID,)),
                now=NOW,
                dry_run=False,
            )

        assert [invocation.invocation_id for invocation in stuck] == [INVOCATION_ID]

    def test_dry_run_reports_matches_without_producing(self) -> None:
        _insert_row(
            team_id=self.team.pk,
            invocation_id=INVOCATION_ID,
            status="running",
            version=1,
            scheduled_at=NOW - timedelta(hours=48),
        )

        with patch("products.cdp.backend.services.stuck_invocations.producer_scope") as mock_scope:
            stuck = unstick_invocations(_scope(self.team.pk), now=NOW, dry_run=True)

        assert [invocation.invocation_id for invocation in stuck] == [INVOCATION_ID]
        mock_scope.assert_not_called()

    def test_commit_produces_one_terminal_row_per_invocation(self) -> None:
        _insert_row(
            team_id=self.team.pk,
            invocation_id=INVOCATION_ID,
            status="running",
            version=1,
            scheduled_at=NOW - timedelta(hours=48),
        )
        producer = MagicMock()

        with patch("products.cdp.backend.services.stuck_invocations.producer_scope") as mock_scope:
            mock_scope.return_value.__enter__.return_value = producer
            unstick_invocations(_scope(self.team.pk), now=NOW, dry_run=False)

        producer.produce.assert_called_once()
        kwargs = producer.produce.call_args.kwargs
        assert kwargs["key"] == INVOCATION_ID
        assert kwargs["data"]["status"] == "failed"
        assert kwargs["data"]["error_kind"] == STUCK_INVOCATION_ERROR_KIND


class TestBuildTerminalRow(SimpleTestCase):
    def _invocation(self, *, version: int, invocation_globals: str = "H4sIAAAA") -> StuckInvocation:
        return StuckInvocation(
            invocation_id=INVOCATION_ID,
            function_id=FUNCTION_ID,
            parent_run_id="",
            attempts=0,
            is_retry=0,
            scheduled_at=NOW - timedelta(hours=48),
            first_scheduled_at=NOW - timedelta(hours=48),
            started_at=NOW - timedelta(hours=48),
            event_uuid="",
            distinct_id="user-1",
            person_id="person-1",
            invocation_globals=invocation_globals,
            version=version,
        )

    def test_carries_the_stored_invocation_globals_through_untouched(self) -> None:
        # The rerun paginator rehydrates a replayed invocation from this column,
        # so dropping or re-encoding it here would leave the run un-rerunnable,
        # which is the state this command exists to fix.
        row = build_terminal_row(self._invocation(version=1), scope=_scope(TEAM_ID), now=NOW)

        assert row["invocation_globals"] == "H4sIAAAA"

    def test_version_beats_a_stored_version_ahead_of_the_clock(self) -> None:
        # ReplacingMergeTree keeps the highest version, so a row that does not
        # beat the stored one is accepted by Kafka and then silently ignored.
        ahead = int((NOW + timedelta(days=1)).timestamp() * 1_000_000)

        row = build_terminal_row(self._invocation(version=ahead), scope=_scope(TEAM_ID), now=NOW)

        assert int(row["version"]) == ahead + 1

    def test_keeps_the_original_scheduled_at_so_the_row_lands_in_the_same_partition(self) -> None:
        # PARTITION BY toYYYYMMDD(scheduled_at): stamping "now" instead would
        # scatter an invocation's rows across partitions, so they would never
        # collapse and the row would outlive the retention of the rows it fixes.
        row = build_terminal_row(self._invocation(version=1), scope=_scope(TEAM_ID), now=NOW)

        assert row["scheduled_at"] == "2026-08-18 12:00:00.000000"
        assert row["finished_at"] == "2026-08-20 12:00:00.000000"
