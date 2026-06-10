from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest import TestCase
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.team.production_event_activation import (
    WINDOW_DAYS,
    _mark_teams_ingested_production_event,
    _teams_meeting_criterion,
    evaluate_and_mark_team_batch,
    is_production_host,
)
from posthog.models.team.team import Team

# Fixed `now` for the transition assertions. The value is arbitrary — these
# tests only check that whatever `now` we pass through lands in
# `_last_checked_at` — but it must be a literal so the time-sensitivity
# semgrep rule doesn't flag a bare `datetime.now()` in a test.
_FIXED_NOW = datetime(2026, 6, 5, 12, 0, 0, tzinfo=UTC)

PRODUCTION_HOST = "app.example.com"


@contextmanager
def _mock_capture():
    # `ph_scoped_capture` is itself a context manager that yields the capture
    # function, so the patch has to provide a context manager whose `__enter__`
    # returns a callable. Tests can then assert against that callable directly.
    capture_fn: Any = MagicMock()
    with patch("posthog.models.team.production_event_activation.ph_scoped_capture") as mock_csm:
        mock_csm.return_value.__enter__.return_value = capture_fn
        mock_csm.return_value.__exit__.return_value = False
        yield capture_fn


def _seed_event(
    team_id: int,
    properties: dict[str, Any] | None = None,
    days_ago: float = 1,
    distinct_id: str = "user-0",
) -> None:
    _create_event(
        team=Team.objects.get(id=team_id),
        event="$pageview",
        distinct_id=distinct_id,
        timestamp=datetime.now(tz=UTC) - timedelta(days=days_ago),
        properties=properties or {},
    )
    flush_persons_and_events()


class TestIsProductionHost(TestCase):
    @parameterized.expand(
        [
            ("example.com",),
            ("app.example.com",),
            ("sub.domain.co.uk",),
            ("example.com:8080",),
            ("EXAMPLE.com",),
            ("  example.com  ",),
            ("mylocalbiz.com",),  # contains "local" but isn't a reserved suffix
            ("localhosting.com",),  # starts with "localhost" but is a real domain
            ("myapp.dev",),  # .dev is a real public TLD
            ("8.8.8.8",),
            ("8.8.8.8:443",),
            ("172.15.0.1",),  # just below the 172.16/12 private range
            ("172.32.0.1",),  # just above the 172.16/12 private range
            ("2606:4700::6810:84e5",),
            ("[2606:4700::6810:84e5]:443",),
            ("::ffff:8.8.8.8",),  # IPv4-mapped public address
        ]
    )
    def test_production_hosts(self, host: str) -> None:
        self.assertTrue(is_production_host(host), f"{host!r} should classify as production")

    @parameterized.expand(
        [
            ("",),
            ("   ",),
            ("localhost",),
            ("localhost:3000",),
            ("LOCALHOST",),
            ("app.localhost",),
            ("myapp.local",),
            ("myapp.test",),
            ("service.internal",),
            ("site.invalid",),
            ("site.example",),
            ("box.localdomain",),
            ("router.home.arpa",),
            ("my-laptop",),  # bare machine name
            ("foo:bar",),  # garbage with a colon
            ("127.0.0.1",),
            ("127.0.0.1:8000",),
            ("10.0.0.5",),
            ("192.168.1.10",),
            ("172.16.0.1",),
            ("172.31.255.255",),
            ("169.254.1.1",),
            ("0.0.0.0",),
            ("100.64.0.1",),  # CGNAT (e.g. Tailscale) — stricter than plain RFC 1918
            ("256.1.1.1",),  # malformed IP literal
            ("::1",),
            ("::",),
            ("[::1]:3000",),
            ("fe80::1",),
            ("fd12:3456::1",),
            ("fc00::1",),
            ("::ffff:127.0.0.1",),
            ("::ffff:192.168.0.1",),
        ]
    )
    def test_non_production_hosts(self, host: str) -> None:
        self.assertFalse(is_production_host(host), f"{host!r} should classify as non-production")


class TestTeamsMeetingCriterion(ClickhouseTestMixin, BaseTest):
    def test_empty_input_returns_empty_dict(self) -> None:
        self.assertEqual(_teams_meeting_criterion([]), {})

    def test_team_with_no_events_does_not_qualify(self) -> None:
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {})

    def test_single_production_event_qualifies(self) -> None:
        _seed_event(self.team.id, properties={"$host": PRODUCTION_HOST})
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {self.team.id: PRODUCTION_HOST})

    def test_dev_only_traffic_does_not_qualify(self) -> None:
        for host in ["localhost:3000", "127.0.0.1:8000", "myapp.test", "192.168.1.10"]:
            _seed_event(self.team.id, properties={"$host": host})
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {})

    def test_current_url_fallback_qualifies(self) -> None:
        _seed_event(self.team.id, properties={"$current_url": f"https://{PRODUCTION_HOST}/dashboard?x=1"})
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {self.team.id: PRODUCTION_HOST})

    def test_local_host_takes_precedence_over_production_current_url(self) -> None:
        _seed_event(
            self.team.id,
            properties={"$host": "localhost:3000", "$current_url": f"https://{PRODUCTION_HOST}/page"},
        )
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {})

    def test_event_without_host_signal_does_not_qualify(self) -> None:
        _seed_event(self.team.id, properties={"$lib": "posthog-python"})
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {})

    def test_events_outside_window_do_not_count(self) -> None:
        _seed_event(self.team.id, properties={"$host": PRODUCTION_HOST}, days_ago=WINDOW_DAYS + 1)
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {})

    def test_mixed_dev_and_production_traffic_qualifies_with_production_host(self) -> None:
        _seed_event(self.team.id, properties={"$host": "myapp.test"})
        _seed_event(self.team.id, properties={"$host": PRODUCTION_HOST})
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {self.team.id: PRODUCTION_HOST})

    def test_only_listed_teams_are_evaluated(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        _seed_event(self.team.id, properties={"$host": PRODUCTION_HOST})
        _seed_event(other_team.id, properties={"$host": PRODUCTION_HOST})

        # other_team has production events but isn't in the input set, so isn't returned.
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {self.team.id: PRODUCTION_HOST})


class TestMarkTeamsIngestedProductionEvent(BaseTest):
    def test_empty_input_returns_zero(self) -> None:
        with _mock_capture() as capture:
            self.assertEqual(_mark_teams_ingested_production_event({}, now=_FIXED_NOW), 0)
            capture.assert_not_called()

    def test_unflagged_team_is_marked_and_emits(self) -> None:
        now = _FIXED_NOW
        self.assertFalse(self.team.ingested_production_event)

        with _mock_capture() as capture:
            marked = _mark_teams_ingested_production_event({self.team.id: PRODUCTION_HOST}, now=now)

        self.team.refresh_from_db()
        self.assertEqual(marked, 1)
        self.assertTrue(self.team.ingested_production_event)
        self.assertEqual(self.team.ingested_production_event_last_checked_at, now)
        capture.assert_called_once()
        ((), kwargs) = capture.call_args
        self.assertEqual(kwargs["event"], "first team production event ingested")
        self.assertEqual(kwargs["distinct_id"], str(self.team.uuid))
        self.assertEqual(kwargs["properties"]["production_host"], PRODUCTION_HOST)

    def test_already_flagged_team_is_noop(self) -> None:
        self.team.ingested_production_event = True
        self.team.save(update_fields=["ingested_production_event"])

        with _mock_capture() as capture:
            marked = _mark_teams_ingested_production_event({self.team.id: PRODUCTION_HOST}, now=_FIXED_NOW)

        self.assertEqual(marked, 0)
        capture.assert_not_called()

    def test_mix_of_flagged_and_unflagged_only_marks_unflagged(self) -> None:
        unflagged = self.team
        flagged = Team.objects.create(organization=self.organization, name="flagged", ingested_production_event=True)

        with _mock_capture() as capture:
            marked = _mark_teams_ingested_production_event(
                {unflagged.id: PRODUCTION_HOST, flagged.id: PRODUCTION_HOST}, now=_FIXED_NOW
            )

        self.assertEqual(marked, 1)
        unflagged.refresh_from_db()
        flagged.refresh_from_db()
        self.assertTrue(unflagged.ingested_production_event)
        self.assertTrue(flagged.ingested_production_event)
        capture.assert_called_once()


class TestEvaluateAndMarkTeamBatch(ClickhouseTestMixin, BaseTest):
    def test_empty_batch_is_noop(self) -> None:
        self.assertEqual(evaluate_and_mark_team_batch([], now=_FIXED_NOW), (0, 0))

    def test_qualifying_team_is_flagged(self) -> None:
        _seed_event(self.team.id, properties={"$host": PRODUCTION_HOST})
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
        _seed_event(self.team.id, properties={"$host": "localhost:3000"})
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
