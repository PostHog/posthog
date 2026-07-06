from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest import TestCase
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.team.production_event_activation import (
    MOBILE_LIB_USERS_THRESHOLD,
    SERVER_LIB_USERS_THRESHOLD,
    WINDOW_DAYS,
    ProductionTrafficSignal,
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
PRODUCTION_HOST_SIGNAL = ProductionTrafficSignal(kind="production_host", production_host=PRODUCTION_HOST)


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
) -> datetime:
    # `now()` lives in this helper (not a `test_*` body) on purpose: tests that
    # need the event's instant read it from the return value instead of
    # recomputing it, which keeps them off the time-sensitivity semgrep rule.
    timestamp = datetime.now(tz=UTC) - timedelta(days=days_ago)
    _create_event(
        team=Team.objects.get(id=team_id),
        event="$pageview",
        distinct_id=distinct_id,
        timestamp=timestamp,
        properties=properties or {},
    )
    flush_persons_and_events()
    return timestamp


def _seed_mobile_events(team_id: int, user_count: int, is_emulator: Any = False) -> None:
    for i in range(user_count):
        _seed_event(
            team_id,
            properties={"$lib": "posthog-ios", "$is_emulator": is_emulator},
            distinct_id=f"mobile-user-{i}",
        )


def _seed_server_events(team_id: int, user_count: int, lib: str = "posthog-python") -> None:
    for i in range(user_count):
        _seed_event(team_id, properties={"$lib": lib}, distinct_id=f"server-user-{i}")


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
            ("example.com.",),  # trailing-dot FQDN of a real domain is still production
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
            ("localhost.",),  # trailing dots must not defeat the deny rules
            ("localhost.:3000",),
            ("app.localhost.",),
            ("myapp.test.",),
            ("127.0.0.1.",),
            ("192.168.1.10.",),
            ("abc123.ngrok-free.app",),  # dev tunnels
            ("tunnel.ngrok.io",),
            ("foo.trycloudflare.com",),
            ("bar.loca.lt",),
            ("127.0.0.1.nip.io",),  # wildcard DNS to an embedded private IP
            ("myhost.ts.net",),  # tailnet-only host
            ("app.lvh.me",),
            ("a" * 300 + ".com",),  # longer than any valid hostname — crafted input
        ]
    )
    def test_non_production_hosts(self, host: str) -> None:
        self.assertFalse(is_production_host(host), f"{host!r} should classify as non-production")


class TestTeamsMeetingCriterion(ClickhouseTestMixin, BaseTest):
    def test_empty_input_returns_empty_dict(self) -> None:
        self.assertEqual(_teams_meeting_criterion([]), {})

    def test_team_with_no_events_does_not_qualify(self) -> None:
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {})

    def _assert_web_qualifiers(self, result: dict[int, ProductionTrafficSignal], expected: dict[int, str]) -> None:
        # Web signals carry a time-dependent `converted_at`, so compare every
        # field except that one; `converted_at` has dedicated tests below.
        self.assertEqual(set(result), set(expected))
        for team_id, host in expected.items():
            self.assertEqual(result[team_id].kind, "production_host")
            self.assertEqual(result[team_id].production_host, host)
            self.assertIsNotNone(result[team_id].converted_at)

    def test_single_production_event_qualifies(self) -> None:
        _seed_event(self.team.id, properties={"$host": PRODUCTION_HOST})
        self._assert_web_qualifiers(_teams_meeting_criterion([self.team.id]), {self.team.id: PRODUCTION_HOST})

    def test_web_signal_carries_earliest_production_event_timestamp(self) -> None:
        # The conversion instant is the earliest production-host event in the
        # window; a later production event must not move it, and a dev event in
        # between must not become it.
        earliest = _seed_event(self.team.id, properties={"$host": PRODUCTION_HOST}, days_ago=5)
        _seed_event(self.team.id, properties={"$host": "localhost:3000"}, days_ago=4)
        _seed_event(self.team.id, properties={"$host": PRODUCTION_HOST}, days_ago=2)

        signal = _teams_meeting_criterion([self.team.id])[self.team.id]
        self.assertEqual(signal.kind, "production_host")
        self.assertIsNotNone(signal.converted_at)
        assert signal.converted_at is not None  # narrow for the subtraction below
        self.assertLess(abs((signal.converted_at - earliest).total_seconds()), 1)

    def test_mobile_signal_has_no_conversion_timestamp(self) -> None:
        # Only the web leg resolves a precise instant; mobile/server stay None.
        _seed_mobile_events(self.team.id, user_count=MOBILE_LIB_USERS_THRESHOLD)
        signal = _teams_meeting_criterion([self.team.id])[self.team.id]
        self.assertEqual(signal.kind, "mobile_lib_users")
        self.assertIsNone(signal.converted_at)

    def test_dev_only_traffic_does_not_qualify(self) -> None:
        for host in ["localhost:3000", "127.0.0.1:8000", "myapp.test", "192.168.1.10"]:
            _seed_event(self.team.id, properties={"$host": host})
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {})

    def test_current_url_fallback_qualifies(self) -> None:
        _seed_event(self.team.id, properties={"$current_url": f"https://{PRODUCTION_HOST}/dashboard?x=1"})
        self._assert_web_qualifiers(_teams_meeting_criterion([self.team.id]), {self.team.id: PRODUCTION_HOST})

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
        self._assert_web_qualifiers(_teams_meeting_criterion([self.team.id]), {self.team.id: PRODUCTION_HOST})

    def test_mobile_users_at_threshold_qualify(self) -> None:
        _seed_mobile_events(self.team.id, user_count=MOBILE_LIB_USERS_THRESHOLD)
        self.assertEqual(
            _teams_meeting_criterion([self.team.id]),
            {self.team.id: ProductionTrafficSignal(kind="mobile_lib_users", distinct_count=MOBILE_LIB_USERS_THRESHOLD)},
        )

    def test_mobile_users_below_threshold_do_not_qualify(self) -> None:
        _seed_mobile_events(self.team.id, user_count=MOBILE_LIB_USERS_THRESHOLD - 1)
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {})

    def test_mobile_qualifies_without_device_id_or_emulator_flag(self) -> None:
        # Regression: mobile SDKs don't put $device_id in event properties and
        # most events omit $is_emulator — these events must still count.
        for i in range(MOBILE_LIB_USERS_THRESHOLD):
            _seed_event(self.team.id, properties={"$lib": "posthog-ios"}, distinct_id=f"mobile-user-{i}")
        signal = _teams_meeting_criterion([self.team.id])[self.team.id]
        self.assertEqual(signal.kind, "mobile_lib_users")
        self.assertEqual(signal.distinct_count, MOBILE_LIB_USERS_THRESHOLD)

    @parameterized.expand([("boolean", True), ("stringly", "true")])
    def test_emulator_flagged_traffic_is_dropped(self, _name: str, is_emulator: Any) -> None:
        # Events affirmatively flagged as emulators don't count, even well above
        # the threshold — a developer's simulator runs are not production.
        _seed_mobile_events(self.team.id, user_count=MOBILE_LIB_USERS_THRESHOLD + 2, is_emulator=is_emulator)
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {})

    def test_mobile_counts_distinct_users(self) -> None:
        # The unit is distinct_id: many events from a few ids stay below the bar.
        for i in range(MOBILE_LIB_USERS_THRESHOLD + 5):
            _seed_event(
                self.team.id,
                properties={"$lib": "posthog-ios", "$is_emulator": False},
                distinct_id="mobile-user-0" if i % 2 else "mobile-user-1",
            )
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {})

    def test_non_mobile_lib_users_do_not_count_toward_mobile_leg(self) -> None:
        # Plenty of distinct users on a non-mobile, non-server dev lib must not
        # drift into the mobile leg — it only counts allowlisted mobile SDKs.
        for i in range(MOBILE_LIB_USERS_THRESHOLD + 5):
            _seed_event(
                self.team.id,
                properties={"$lib": "web", "$host": "localhost:3000"},
                distinct_id=f"web-user-{i}",
            )
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {})

    def test_server_lib_users_at_threshold_qualify(self) -> None:
        _seed_server_events(self.team.id, user_count=SERVER_LIB_USERS_THRESHOLD)
        self.assertEqual(
            _teams_meeting_criterion([self.team.id]),
            {self.team.id: ProductionTrafficSignal(kind="server_lib_users", distinct_count=SERVER_LIB_USERS_THRESHOLD)},
        )

    def test_server_lib_users_below_threshold_do_not_qualify(self) -> None:
        _seed_server_events(self.team.id, user_count=SERVER_LIB_USERS_THRESHOLD - 1)
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {})

    def test_web_lib_users_do_not_count_toward_server_leg(self) -> None:
        # Many distinct anonymous users on a dev host (e.g. an e2e suite) must not
        # drift into the server leg — it only counts allowlisted server SDKs.
        for i in range(SERVER_LIB_USERS_THRESHOLD + 5):
            _seed_event(
                self.team.id,
                properties={"$lib": "web", "$host": "localhost:3000"},
                distinct_id=f"e2e-user-{i}",
            )
        self.assertEqual(_teams_meeting_criterion([self.team.id]), {})

    def test_production_host_takes_precedence_over_other_signals(self) -> None:
        _seed_mobile_events(self.team.id, user_count=MOBILE_LIB_USERS_THRESHOLD)
        _seed_server_events(self.team.id, user_count=SERVER_LIB_USERS_THRESHOLD)
        _seed_event(self.team.id, properties={"$host": PRODUCTION_HOST})
        self._assert_web_qualifiers(_teams_meeting_criterion([self.team.id]), {self.team.id: PRODUCTION_HOST})

    def test_mobile_takes_precedence_over_server(self) -> None:
        # Both legs cross their thresholds with no web host; mobile must win, per
        # the documented web > mobile > server precedence.
        _seed_mobile_events(self.team.id, user_count=MOBILE_LIB_USERS_THRESHOLD)
        _seed_server_events(self.team.id, user_count=SERVER_LIB_USERS_THRESHOLD)
        self.assertEqual(
            _teams_meeting_criterion([self.team.id]),
            {self.team.id: ProductionTrafficSignal(kind="mobile_lib_users", distinct_count=MOBILE_LIB_USERS_THRESHOLD)},
        )

        other_team = Team.objects.create(organization=self.organization, name="other")
        _seed_event(self.team.id, properties={"$host": PRODUCTION_HOST})
        _seed_event(other_team.id, properties={"$host": PRODUCTION_HOST})

        # other_team has production events but isn't in the input set, so isn't returned.
        self._assert_web_qualifiers(_teams_meeting_criterion([self.team.id]), {self.team.id: PRODUCTION_HOST})


class TestMarkTeamsIngestedProductionEvent(BaseTest):
    def test_empty_input_returns_zero(self) -> None:
        with _mock_capture() as capture:
            self.assertEqual(_mark_teams_ingested_production_event({}, now=_FIXED_NOW), 0)
            capture.assert_not_called()

    def test_unflagged_team_is_marked_and_emits(self) -> None:
        now = _FIXED_NOW
        self.assertFalse(self.team.ingested_production_event)

        with _mock_capture() as capture:
            marked = _mark_teams_ingested_production_event({self.team.id: PRODUCTION_HOST_SIGNAL}, now=now)

        self.team.refresh_from_db()
        self.assertEqual(marked, 1)
        self.assertTrue(self.team.ingested_production_event)
        self.assertEqual(self.team.ingested_production_event_last_checked_at, now)
        capture.assert_called_once()
        ((), kwargs) = capture.call_args
        self.assertEqual(kwargs["event"], "first team production event ingested")
        self.assertEqual(kwargs["distinct_id"], str(self.team.uuid))
        # No `converted_at` on this signal, so the emit falls back to run time.
        self.assertEqual(kwargs["timestamp"], now)
        self.assertEqual(
            kwargs["properties"],
            {
                "detection_signal": "production_host",
                "production_host": PRODUCTION_HOST,
                "window_days": WINDOW_DAYS,
                "team": str(self.team.uuid),
            },
        )

    def test_web_signal_emits_with_conversion_timestamp(self) -> None:
        converted_at = datetime(2026, 5, 30, 8, 0, 0, tzinfo=UTC)
        signal = ProductionTrafficSignal(
            kind="production_host", production_host=PRODUCTION_HOST, converted_at=converted_at
        )

        with _mock_capture() as capture:
            _mark_teams_ingested_production_event({self.team.id: signal}, now=_FIXED_NOW)

        ((), kwargs) = capture.call_args
        # Web leg stamps the conversion instant, not the run time.
        self.assertEqual(kwargs["timestamp"], converted_at)
        self.assertNotEqual(kwargs["timestamp"], _FIXED_NOW)

    def test_mobile_signal_emits_distinct_count(self) -> None:
        signal = ProductionTrafficSignal(kind="mobile_lib_users", distinct_count=4)

        with _mock_capture() as capture:
            marked = _mark_teams_ingested_production_event({self.team.id: signal}, now=_FIXED_NOW)

        self.assertEqual(marked, 1)
        ((), kwargs) = capture.call_args
        # Mobile leg has no conversion instant, so it stamps the run time.
        self.assertEqual(kwargs["timestamp"], _FIXED_NOW)
        self.assertEqual(
            kwargs["properties"],
            {
                "detection_signal": "mobile_lib_users",
                "distinct_count": 4,
                "window_days": WINDOW_DAYS,
                "team": str(self.team.uuid),
            },
        )

    def test_capture_failure_for_one_team_does_not_drop_the_rest(self) -> None:
        other = Team.objects.create(organization=self.organization, name="other")

        with _mock_capture() as capture:
            capture.side_effect = [Exception("boom"), None]
            marked = _mark_teams_ingested_production_event(
                {self.team.id: PRODUCTION_HOST_SIGNAL, other.id: PRODUCTION_HOST_SIGNAL}, now=_FIXED_NOW
            )

        self.assertEqual(marked, 2)
        self.assertEqual(capture.call_count, 2)
        self.team.refresh_from_db()
        other.refresh_from_db()
        self.assertTrue(self.team.ingested_production_event)
        self.assertTrue(other.ingested_production_event)

    def test_already_flagged_team_is_noop(self) -> None:
        self.team.ingested_production_event = True
        self.team.save(update_fields=["ingested_production_event"])

        with _mock_capture() as capture:
            marked = _mark_teams_ingested_production_event({self.team.id: PRODUCTION_HOST_SIGNAL}, now=_FIXED_NOW)

        self.assertEqual(marked, 0)
        capture.assert_not_called()

    def test_mix_of_flagged_and_unflagged_only_marks_unflagged(self) -> None:
        unflagged = self.team
        flagged = Team.objects.create(organization=self.organization, name="flagged", ingested_production_event=True)

        with _mock_capture() as capture:
            marked = _mark_teams_ingested_production_event(
                {unflagged.id: PRODUCTION_HOST_SIGNAL, flagged.id: PRODUCTION_HOST_SIGNAL}, now=_FIXED_NOW
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

    def test_web_qualifier_emits_at_conversion_time(self) -> None:
        # End-to-end through the batch: the activation event is stamped at the
        # production event's own time, not the run time we pass as `now`.
        conversion_time = _seed_event(self.team.id, properties={"$host": PRODUCTION_HOST}, days_ago=3)

        with _mock_capture() as capture:
            evaluate_and_mark_team_batch([self.team.id], now=_FIXED_NOW)

        ((), kwargs) = capture.call_args
        self.assertEqual(kwargs["event"], "first team production event ingested")
        emitted = kwargs["timestamp"]
        self.assertIsNotNone(emitted)
        assert emitted is not None  # narrow for the subtraction below
        self.assertLess(abs((emitted - conversion_time).total_seconds()), 1)

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
