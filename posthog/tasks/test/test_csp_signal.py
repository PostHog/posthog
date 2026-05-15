from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.tasks.csp_signal import (
    CSP_SIGNAL_DEDUP_TTL_SECONDS,
    CSP_SIGNAL_FIELD_MAX_LENGTH,
    CspReport,
    _daily_count_key,
    _dedup_key,
    _enabled_cache_key,
    emit_csp_violation_signals_task,
    enqueue_csp_violation_signals,
)


def _build_description(properties: dict) -> str:
    return CspReport.from_properties(properties).description()


def _build_extra(properties: dict) -> dict:
    return CspReport.from_properties(properties).extra()


def _fingerprint(properties: dict) -> str:
    return CspReport.from_properties(properties).fingerprint()


def _csp_properties(**overrides: Any) -> dict:
    base = {
        "$csp_violated_directive": "script-src",
        "$csp_effective_directive": "script-src",
        "$csp_blocked_url": "https://evil.example.com/x.js",
        "$csp_document_url": "https://example.com/page",
        "$csp_source_file": "https://example.com/page.html",
        "$csp_line_number": 42,
        "$csp_column_number": 7,
        "$csp_disposition": "enforce",
        "$csp_user_agent": "Mozilla/5.0",
        "$csp_original_policy": "default-src 'self'; script-src 'self'",
        "$csp_referrer": "https://example.com/start",
    }
    base.update(overrides)
    return base


class TestCSPSignalFingerprint(BaseTest):
    @parameterized.expand(
        [
            ("same_violation_same_fingerprint", _csp_properties(), _csp_properties(), True),
            (
                "different_blocked_url_different_fingerprint",
                _csp_properties(),
                _csp_properties(**{"$csp_blocked_url": "https://other.example.com/x.js"}),
                False,
            ),
            (
                "different_directive_different_fingerprint",
                _csp_properties(),
                _csp_properties(**{"$csp_violated_directive": "img-src"}),
                False,
            ),
            (
                "different_document_url_different_fingerprint",
                _csp_properties(),
                _csp_properties(**{"$csp_document_url": "https://example.com/other"}),
                False,
            ),
            (
                "irrelevant_fields_dont_affect_fingerprint",
                _csp_properties(),
                _csp_properties(**{"$csp_user_agent": "Other UA", "$csp_line_number": 999}),
                True,
            ),
        ]
    )
    def test_fingerprint_uniqueness(self, _name: str, a: dict, b: dict, should_match: bool) -> None:
        assert (_fingerprint(a) == _fingerprint(b)) is should_match


class TestCSPSignalDescription(BaseTest):
    def test_description_includes_key_fields(self) -> None:
        description = _build_description(_csp_properties())
        assert "script-src" in description
        assert "https://evil.example.com/x.js" in description
        assert "https://example.com/page" in description
        assert "enforce" in description
        assert "https://example.com/page.html:42:7" in description
        assert "Mozilla/5.0" in description

    def test_description_has_cause_fix_triage_sections(self) -> None:
        description = _build_description(_csp_properties())
        assert "## Cause" in description
        assert "## Suggested fix" in description
        assert "## Triage" in description

    def test_description_includes_suggested_directive_snippet_with_blocked_origin(self) -> None:
        description = _build_description(_csp_properties())
        # blocked URL is https://evil.example.com/x.js → suggest adding https://evil.example.com
        assert "https://evil.example.com" in description
        assert "script-src 'self' https://evil.example.com;" in description

    def test_description_falls_back_when_blocked_url_has_no_origin(self) -> None:
        description = _build_description(_csp_properties(**{"$csp_blocked_url": "inline"}))
        # No scheme://host means we don't construct a snippet — fallback prose
        assert "script-src 'self' inline" not in description
        assert "Decide whether the blocked resource is legitimate" in description

    def test_description_handles_missing_fields(self) -> None:
        description = _build_description({})
        assert "unknown directive" in description
        assert "unknown resource" in description
        assert "unknown page" in description

    def test_extra_payload_shape(self) -> None:
        extra = _build_extra(_csp_properties())
        assert extra["document_url"] == "https://example.com/page"
        assert extra["violated_directive"] == "script-src"
        assert extra["blocked_url"] == "https://evil.example.com/x.js"
        assert extra["line_number"] == 42.0
        assert extra["column_number"] == 7.0
        assert extra["disposition"] == "enforce"
        assert extra["user_agent"] == "Mozilla/5.0"
        assert extra["original_policy"] == "default-src 'self'; script-src 'self'"
        assert extra["referrer"] == "https://example.com/start"

    def test_extra_payload_handles_missing(self) -> None:
        extra = _build_extra({})
        assert extra["document_url"] is None
        assert extra["line_number"] is None
        assert extra["column_number"] is None
        assert extra["original_policy"] is None
        assert extra["referrer"] is None

    @parameterized.expand(
        [
            ("nan", "NaN"),
            ("positive_infinity", "Infinity"),
            ("negative_infinity", "-Infinity"),
        ]
    )
    def test_extra_payload_rejects_non_finite_numbers(self, _name: str, value: str) -> None:
        extra = _build_extra(_csp_properties(**{"$csp_line_number": value}))
        assert extra["line_number"] is None


class TestCSPSignalFieldLengthCap(BaseTest):
    def test_oversized_field_is_truncated_in_extra(self) -> None:
        huge = "x" * (CSP_SIGNAL_FIELD_MAX_LENGTH * 4)
        extra = _build_extra(_csp_properties(**{"$csp_blocked_url": huge}))
        assert extra["blocked_url"] is not None
        assert len(extra["blocked_url"]) == CSP_SIGNAL_FIELD_MAX_LENGTH

    def test_oversized_field_is_truncated_in_description(self) -> None:
        huge = "x" * (CSP_SIGNAL_FIELD_MAX_LENGTH * 4)
        description = _build_description(_csp_properties(**{"$csp_blocked_url": huge}))
        # description embeds the blocked_url once; total description length is bounded by
        # cap × number_of_fields + the constant template text.
        assert len(description) < (CSP_SIGNAL_FIELD_MAX_LENGTH * 10)


class TestCSPSignalFingerprintRobustness(BaseTest):
    def test_empty_fields_do_not_collapse_with_pipe_embedded_fields(self) -> None:
        empty = _csp_properties(
            **{
                "$csp_violated_directive": None,
                "$csp_blocked_url": None,
                "$csp_document_url": None,
                "$csp_source_file": None,
            }
        )
        pipe_smuggled = _csp_properties(
            **{
                "$csp_violated_directive": "|",
                "$csp_blocked_url": "|",
                "$csp_document_url": "|",
                "$csp_source_file": "",
            }
        )
        assert _fingerprint(empty) != _fingerprint(pipe_smuggled)


def _enable_csp_signals(team_id: int) -> None:
    cache.set(_enabled_cache_key(team_id), True, 60)


def _disable_csp_signals(team_id: int) -> None:
    cache.set(_enabled_cache_key(team_id), False, 60)


class TestCSPSignalThrottle(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        from posthog.redis import get_client

        client = get_client()
        for pattern in ("csp_signal_dedup:*", "csp_signal_daily_count:*"):
            for key in client.scan_iter(match=pattern):
                client.delete(key)
        cache.delete(_enabled_cache_key(self.team.id))
        _enable_csp_signals(self.team.id)

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signals_task.delay")
    def test_first_violation_enqueues_one_task(self, mock_delay: MagicMock) -> None:
        enqueued = enqueue_csp_violation_signals(self.team.id, [_csp_properties()])
        assert enqueued == 1
        mock_delay.assert_called_once()
        kwargs = mock_delay.call_args.kwargs
        assert kwargs["team_id"] == self.team.id
        assert len(kwargs["signals"]) == 1

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signals_task.delay")
    def test_duplicate_violation_is_throttled(self, mock_delay: MagicMock) -> None:
        first = enqueue_csp_violation_signals(self.team.id, [_csp_properties()])
        second = enqueue_csp_violation_signals(self.team.id, [_csp_properties()])
        assert first == 1
        assert second == 0
        mock_delay.assert_called_once()

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signals_task.delay")
    def test_batch_of_distinct_violations_enqueues_one_task_with_all(self, mock_delay: MagicMock) -> None:
        distinct_violations = [
            _csp_properties(),
            _csp_properties(**{"$csp_blocked_url": "https://other.example.com/x.js"}),
            _csp_properties(**{"$csp_document_url": "https://example.com/other"}),
        ]
        enqueued = enqueue_csp_violation_signals(self.team.id, distinct_violations)
        assert enqueued == 3
        mock_delay.assert_called_once()
        kwargs = mock_delay.call_args.kwargs
        assert len(kwargs["signals"]) == 3

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signals_task.delay")
    def test_batch_with_duplicates_only_enqueues_new(self, mock_delay: MagicMock) -> None:
        violations = [
            _csp_properties(),
            _csp_properties(),
            _csp_properties(**{"$csp_blocked_url": "https://other.example.com/x.js"}),
        ]
        enqueued = enqueue_csp_violation_signals(self.team.id, violations)
        assert enqueued == 2
        mock_delay.assert_called_once()
        kwargs = mock_delay.call_args.kwargs
        assert len(kwargs["signals"]) == 2

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signals_task.delay")
    def test_throttle_is_per_team(self, mock_delay: MagicMock) -> None:
        from posthog.models import Organization, Team

        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")
        _enable_csp_signals(other_team.id)

        enqueue_csp_violation_signals(self.team.id, [_csp_properties()])
        enqueue_csp_violation_signals(other_team.id, [_csp_properties()])
        assert mock_delay.call_count == 2

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signals_task.delay")
    def test_ttl_is_24_hours(self, mock_delay: MagicMock) -> None:
        from posthog.redis import get_client

        properties = _csp_properties()
        enqueue_csp_violation_signals(self.team.id, [properties])

        key = _dedup_key(self.team.id, _fingerprint(properties))
        ttl = get_client().ttl(key)
        assert 0 < ttl <= CSP_SIGNAL_DEDUP_TTL_SECONDS

    @patch("posthog.tasks.csp_signal.get_client")
    @patch("posthog.tasks.csp_signal.emit_csp_violation_signals_task.delay")
    def test_redis_failure_skips_violation(self, mock_delay: MagicMock, mock_get_client: MagicMock) -> None:
        # Redis outage hits the daily-count reservation first (atomic INCRBY)
        # — and an outage would fail every subsequent call too.
        fake_client = mock_get_client.return_value
        fake_client.incrby.side_effect = RuntimeError("redis down")

        result = enqueue_csp_violation_signals(self.team.id, [_csp_properties()])
        assert result == 0
        mock_delay.assert_not_called()

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signals_task.delay", side_effect=RuntimeError("broker down"))
    def test_celery_dispatch_failure_releases_dedup_keys_and_reservation(self, _mock_delay: MagicMock) -> None:
        from posthog.redis import get_client

        properties = _csp_properties()
        result = enqueue_csp_violation_signals(self.team.id, [properties])
        assert result == 0

        client = get_client()
        # Dedup key DEL'd so the next request retries.
        key = _dedup_key(self.team.id, _fingerprint(properties))
        assert client.get(key) is None
        # Reserved daily count slot also released.
        count = client.get(_daily_count_key(self.team.id))
        assert count is None or int(count) == 0

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signals_task.delay")
    def test_daily_count_releases_unused_slots_when_all_duplicates(self, mock_delay: MagicMock) -> None:
        from posthog.redis import get_client

        properties = _csp_properties()
        # First call: count goes 0 → 1
        enqueue_csp_violation_signals(self.team.id, [properties])
        # Second call with the same fingerprint: reservation +1, but dedup misses,
        # so the unused slot is released. Count must stay at 1, not 2.
        enqueue_csp_violation_signals(self.team.id, [properties])

        count = get_client().get(_daily_count_key(self.team.id))
        assert count is not None
        assert int(count) == 1
        # Only the first call dispatched a task.
        mock_delay.assert_called_once()

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signals_task.delay")
    def test_daily_count_increments_after_dispatch(self, mock_delay: MagicMock) -> None:
        from posthog.redis import get_client

        enqueue_csp_violation_signals(self.team.id, [_csp_properties()])
        count = get_client().get(_daily_count_key(self.team.id))
        assert count is not None
        assert int(count) == 1

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signals_task.delay")
    def test_daily_cap_drops_violations_once_reached(self, mock_delay: MagicMock) -> None:
        from django.test import override_settings

        from posthog.redis import get_client

        # Seed counter at cap
        get_client().set(_daily_count_key(self.team.id), "3")

        with override_settings(CSP_SIGNAL_DAILY_CAP_PER_TEAM=3):
            result = enqueue_csp_violation_signals(self.team.id, [_csp_properties()])
        assert result == 0
        mock_delay.assert_not_called()

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signals_task.delay")
    def test_daily_cap_partially_drops_when_batch_overflows(self, mock_delay: MagicMock) -> None:
        from django.test import override_settings

        from posthog.redis import get_client

        # Two slots remaining
        get_client().set(_daily_count_key(self.team.id), "8")
        batch = [
            _csp_properties(),
            _csp_properties(**{"$csp_blocked_url": "https://a/x.js"}),
            _csp_properties(**{"$csp_blocked_url": "https://b/x.js"}),
            _csp_properties(**{"$csp_blocked_url": "https://c/x.js"}),
            _csp_properties(**{"$csp_blocked_url": "https://d/x.js"}),
        ]

        with override_settings(CSP_SIGNAL_DAILY_CAP_PER_TEAM=10):
            result = enqueue_csp_violation_signals(self.team.id, batch)

        assert result == 2
        mock_delay.assert_called_once()
        kwargs = mock_delay.call_args.kwargs
        assert len(kwargs["signals"]) == 2
        # Counter advanced from 8 to 10, not 13.
        count = get_client().get(_daily_count_key(self.team.id))
        assert count is not None
        assert int(count) == 10

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signals_task.delay")
    def test_ops_kill_switch_short_circuits_emission(self, mock_delay: MagicMock) -> None:
        from django.test import override_settings

        with override_settings(CSP_SIGNAL_EMISSION_ENABLED=False):
            result = enqueue_csp_violation_signals(self.team.id, [_csp_properties()])
        assert result == 0
        mock_delay.assert_not_called()

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signals_task.delay")
    def test_disabled_team_skips_throttle_and_enqueue(self, mock_delay: MagicMock) -> None:
        _disable_csp_signals(self.team.id)
        result = enqueue_csp_violation_signals(self.team.id, [_csp_properties()])
        assert result == 0
        mock_delay.assert_not_called()

    @patch("posthog.tasks.csp_signal.SignalSourceConfig.is_source_enabled")
    @patch("posthog.tasks.csp_signal.emit_csp_violation_signals_task.delay")
    def test_enabled_check_is_cached(self, mock_delay: MagicMock, mock_is_enabled: MagicMock) -> None:
        cache.delete(_enabled_cache_key(self.team.id))
        mock_is_enabled.return_value = True

        enqueue_csp_violation_signals(self.team.id, [_csp_properties()])
        enqueue_csp_violation_signals(self.team.id, [_csp_properties(**{"$csp_blocked_url": "https://a/x.js"})])
        enqueue_csp_violation_signals(self.team.id, [_csp_properties(**{"$csp_blocked_url": "https://b/x.js"})])

        assert mock_is_enabled.call_count == 1


class TestCSPSignalTask(BaseTest):
    @patch("products.signals.backend.api.emit_signal")
    def test_task_calls_emit_signal_for_each_signal_in_batch(self, mock_emit_signal: MagicMock) -> None:
        async def fake_emit(*args: Any, **kwargs: Any) -> None:
            return None

        mock_emit_signal.side_effect = fake_emit

        emit_csp_violation_signals_task(
            team_id=self.team.id,
            signals=[
                {"source_id": "csp:a", "description": "desc a", "extra": {"document_url": "https://x/a"}},
                {"source_id": "csp:b", "description": "desc b", "extra": {"document_url": "https://x/b"}},
            ],
        )

        assert mock_emit_signal.call_count == 2
        source_ids = [c.kwargs["source_id"] for c in mock_emit_signal.call_args_list]
        assert source_ids == ["csp:a", "csp:b"]
        for c in mock_emit_signal.call_args_list:
            assert c.kwargs["source_product"] == "csp_reporting"
            assert c.kwargs["source_type"] == "violation"
            assert c.kwargs["team"].id == self.team.id

    @patch("products.signals.backend.api.emit_signal")
    def test_task_raises_when_team_missing(self, mock_emit_signal: MagicMock) -> None:
        import pytest

        from posthog.models.scoping.manager import TeamScopeError

        with pytest.raises(TeamScopeError):
            emit_csp_violation_signals_task(
                team_id=999_999_999,
                signals=[{"source_id": "csp:a", "description": "d", "extra": {}}],
            )
        mock_emit_signal.assert_not_called()

    @patch("products.signals.backend.api.emit_signal")
    def test_task_raises_on_soft_time_limit(self, mock_emit_signal: MagicMock) -> None:
        import pytest

        from celery.exceptions import SoftTimeLimitExceeded

        async def time_limit_boom(*args: Any, **kwargs: Any) -> None:
            raise SoftTimeLimitExceeded()

        mock_emit_signal.side_effect = time_limit_boom

        with pytest.raises(SoftTimeLimitExceeded):
            emit_csp_violation_signals_task(
                team_id=self.team.id,
                signals=[
                    {"source_id": "csp:a", "description": "d a", "extra": {}},
                    {"source_id": "csp:b", "description": "d b", "extra": {}},
                ],
            )

        # Loop must stop on the first signal; not retry / not continue silently.
        assert mock_emit_signal.call_count == 1

    @patch("products.signals.backend.api.emit_signal")
    def test_task_continues_after_emit_failure_for_one_signal(self, mock_emit_signal: MagicMock) -> None:
        call_count = {"count": 0}

        async def maybe_boom(*args: Any, **kwargs: Any) -> None:
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise RuntimeError("temporal unavailable")
            return None

        mock_emit_signal.side_effect = maybe_boom

        emit_csp_violation_signals_task(
            team_id=self.team.id,
            signals=[
                {"source_id": "csp:a", "description": "d a", "extra": {}},
                {"source_id": "csp:b", "description": "d b", "extra": {}},
            ],
        )

        assert mock_emit_signal.call_count == 2
