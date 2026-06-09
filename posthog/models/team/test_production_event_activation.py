from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from posthog.models.team.production_event_activation import (
    DISTINCT_USERS_THRESHOLD,
    WINDOW_DAYS,
    _mark_teams_ingested_production_event,
    _teams_meeting_criterion,
    evaluate_and_mark_team_batch,
)
from posthog.models.team.team import Team


@contextmanager
def _mock_capture():
    """Patch `ph_scoped_capture` and yield the mock `capture(...)` callable.

    `ph_scoped_capture` is itself a context manager that yields the capture
    function, so the patch has to provide a context manager whose `__enter__`
    returns a callable. Tests can then assert against that callable directly.
    """
    capture_fn: Any = MagicMock()
    with patch("posthog.models.team.production_event_activation.ph_scoped_capture") as mock_csm:
        mock_csm.return_value.__enter__.return_value = capture_fn
        mock_csm.return_value.__exit__.return_value = False
        yield capture_fn


def _seed_events_for_team(team_id: int, distinct_id_count: int, days_ago: float = 1) -> None:
    """Seed `distinct_id_count` distinct users worth of events into ClickHouse."""
    timestamp = datetime.now(tz=UTC) - timedelta(days=days_ago)
    for i in range(distinct_id_count):
        _create_event(
            team=Team.objects.get(id=team_id),
            event="$pageview",
            distinct_id=f"user-{i}",
            timestamp=timestamp,
        )
    flush_persons_and_events()


class TestTeamsMeetingCriterion(ClickhouseTestMixin, BaseTest):
    def test_empty_input_returns_empty_set(self) -> None:
        self.assertEqual(_teams_meeting_criterion([]), set())

    def test_team_with_no_events_does_not_qualify(self) -> None:
        self.assertEqual(_teams_meeting_criterion([self.team.id]), set())

    def test_team_below_threshold_does_not_qualify(self) -> None:
        _seed_events_for_team(self.team.id, distinct_id_count=DISTINCT_USERS_THRESHOLD - 1)
        self.assertEqual(_teams_meeting_criterion([self.team.id]), set())

    def test_team_at_threshold_qualifies(self) -> None:
        _seed_events_for_team(self.team.id, distinct_id_count=DISTINCT_USERS_THRESHOLD)
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {self.team.id})

    def test_events_outside_window_do_not_count(self) -> None:
        _seed_events_for_team(self.team.id, distinct_id_count=DISTINCT_USERS_THRESHOLD, days_ago=WINDOW_DAYS + 1)
        self.assertEqual(_teams_meeting_criterion([self.team.id]), set())

    def test_only_listed_teams_are_evaluated(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        _seed_events_for_team(self.team.id, distinct_id_count=DISTINCT_USERS_THRESHOLD)
        _seed_events_for_team(other_team.id, distinct_id_count=DISTINCT_USERS_THRESHOLD)

        # other_team has events but isn't in the input set, so isn't returned.
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {self.team.id})


class TestMarkTeamsIngestedProductionEvent(BaseTest):
    def test_empty_input_returns_zero(self) -> None:
        with _mock_capture() as capture:
            self.assertEqual(_mark_teams_ingested_production_event([], now=datetime.now(tz=UTC)), 0)
            capture.assert_not_called()

    def test_unflagged_team_is_marked_and_emits(self) -> None:
        now = datetime.now(tz=UTC)
        self.assertFalse(self.team.ingested_production_event)

        with _mock_capture() as capture:
            marked = _mark_teams_ingested_production_event([self.team.id], now=now)

        self.team.refresh_from_db()
        self.assertEqual(marked, 1)
        self.assertTrue(self.team.ingested_production_event)
        self.assertEqual(self.team.ingested_production_event_last_checked_at, now)
        capture.assert_called_once()
        ((), kwargs) = capture.call_args
        self.assertEqual(kwargs["event"], "first team production event ingested")
        self.assertEqual(kwargs["distinct_id"], str(self.team.uuid))

    def test_already_flagged_team_is_noop(self) -> None:
        self.team.ingested_production_event = True
        self.team.save(update_fields=["ingested_production_event"])

        with _mock_capture() as capture:
            marked = _mark_teams_ingested_production_event([self.team.id], now=datetime.now(tz=UTC))

        self.assertEqual(marked, 0)
        capture.assert_not_called()

    def test_mix_of_flagged_and_unflagged_only_marks_unflagged(self) -> None:
        unflagged = self.team
        flagged = Team.objects.create(organization=self.organization, name="flagged", ingested_production_event=True)

        with _mock_capture() as capture:
            marked = _mark_teams_ingested_production_event([unflagged.id, flagged.id], now=datetime.now(tz=UTC))

        self.assertEqual(marked, 1)
        unflagged.refresh_from_db()
        flagged.refresh_from_db()
        self.assertTrue(unflagged.ingested_production_event)
        self.assertTrue(flagged.ingested_production_event)
        capture.assert_called_once()


class TestEvaluateAndMarkTeamBatch(ClickhouseTestMixin, BaseTest):
    def test_empty_batch_is_noop(self) -> None:
        self.assertEqual(evaluate_and_mark_team_batch([], now=datetime.now(tz=UTC)), (0, 0))

    def test_qualifying_team_is_flagged(self) -> None:
        _seed_events_for_team(self.team.id, distinct_id_count=DISTINCT_USERS_THRESHOLD)
        with freeze_time("2026-06-05T12:00:00Z"), _mock_capture():
            qualifying, marked = evaluate_and_mark_team_batch(
                [self.team.id], now=datetime(2026, 6, 5, 12, 0, 0, tzinfo=UTC)
            )

        self.assertEqual(qualifying, 1)
        self.assertEqual(marked, 1)
        self.team.refresh_from_db()
        self.assertTrue(self.team.ingested_production_event)
        self.assertEqual(
            self.team.ingested_production_event_last_checked_at,
            datetime(2026, 6, 5, 12, 0, 0, tzinfo=UTC),
        )

    def test_non_qualifying_team_only_gets_last_checked_at_bumped(self) -> None:
        _seed_events_for_team(self.team.id, distinct_id_count=DISTINCT_USERS_THRESHOLD - 1)
        with freeze_time("2026-06-05T12:00:00Z"):
            qualifying, marked = evaluate_and_mark_team_batch(
                [self.team.id], now=datetime(2026, 6, 5, 12, 0, 0, tzinfo=UTC)
            )

        self.assertEqual(qualifying, 0)
        self.assertEqual(marked, 0)
        self.team.refresh_from_db()
        self.assertFalse(self.team.ingested_production_event)
        self.assertEqual(
            self.team.ingested_production_event_last_checked_at,
            datetime(2026, 6, 5, 12, 0, 0, tzinfo=UTC),
        )
