from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.tasks.csp_signal import (
    CSP_SIGNAL_DEDUP_TTL_SECONDS,
    _build_description,
    _build_extra,
    _dedup_key,
    _fingerprint,
    emit_csp_violation_signal_task,
    enqueue_csp_violation_signal,
)


def _csp_properties(**overrides) -> dict:
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
    def test_fingerprint_uniqueness(self, _name, a, b, should_match):
        assert (_fingerprint(a) == _fingerprint(b)) is should_match


class TestCSPSignalDescription(BaseTest):
    def test_description_includes_key_fields(self):
        description = _build_description(_csp_properties())
        assert "script-src" in description
        assert "https://evil.example.com/x.js" in description
        assert "https://example.com/page" in description
        assert "enforce" in description
        assert "https://example.com/page.html:42:7" in description
        assert "Mozilla/5.0" in description

    def test_description_handles_missing_fields(self):
        description = _build_description({})
        assert "unknown directive" in description
        assert "unknown resource" in description
        assert "unknown page" in description

    def test_extra_payload_shape(self):
        extra = _build_extra(_csp_properties())
        assert extra["document_url"] == "https://example.com/page"
        assert extra["violated_directive"] == "script-src"
        assert extra["blocked_url"] == "https://evil.example.com/x.js"
        assert extra["line_number"] == 42.0
        assert extra["column_number"] == 7.0
        assert extra["disposition"] == "enforce"
        assert extra["user_agent"] == "Mozilla/5.0"

    def test_extra_payload_handles_missing(self):
        extra = _build_extra({})
        assert extra["document_url"] is None
        assert extra["line_number"] is None
        assert extra["column_number"] is None


class TestCSPSignalThrottle(BaseTest):
    def setUp(self):
        super().setUp()
        from posthog.redis import get_client

        # Clear any keys from prior runs
        client = get_client()
        for key in client.scan_iter(match="csp_signal_dedup:*"):
            client.delete(key)

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signal_task.delay")
    def test_first_violation_enqueues_task(self, mock_delay):
        properties = _csp_properties()
        enqueued = enqueue_csp_violation_signal(self.team.id, properties)
        assert enqueued is True
        mock_delay.assert_called_once()

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signal_task.delay")
    def test_duplicate_violation_is_throttled(self, mock_delay):
        properties = _csp_properties()
        first = enqueue_csp_violation_signal(self.team.id, properties)
        second = enqueue_csp_violation_signal(self.team.id, properties)
        assert first is True
        assert second is False
        mock_delay.assert_called_once()

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signal_task.delay")
    def test_distinct_violations_each_enqueue(self, mock_delay):
        enqueue_csp_violation_signal(self.team.id, _csp_properties())
        enqueue_csp_violation_signal(
            self.team.id, _csp_properties(**{"$csp_blocked_url": "https://other.example.com/x.js"})
        )
        assert mock_delay.call_count == 2

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signal_task.delay")
    def test_throttle_is_per_team(self, mock_delay):
        properties = _csp_properties()
        from posthog.models import Organization, Team

        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")

        enqueue_csp_violation_signal(self.team.id, properties)
        enqueue_csp_violation_signal(other_team.id, properties)
        assert mock_delay.call_count == 2

    @patch("posthog.tasks.csp_signal.emit_csp_violation_signal_task.delay")
    def test_ttl_is_24_hours(self, mock_delay):
        from posthog.redis import get_client

        properties = _csp_properties()
        enqueue_csp_violation_signal(self.team.id, properties)

        key = _dedup_key(self.team.id, _fingerprint(properties))
        ttl = get_client().ttl(key)
        assert 0 < ttl <= CSP_SIGNAL_DEDUP_TTL_SECONDS

    @patch("posthog.tasks.csp_signal.get_client")
    @patch("posthog.tasks.csp_signal.emit_csp_violation_signal_task.delay")
    def test_redis_failure_doesnt_enqueue(self, mock_delay, mock_get_client):
        mock_get_client.side_effect = RuntimeError("redis down")
        result = enqueue_csp_violation_signal(self.team.id, _csp_properties())
        assert result is False
        mock_delay.assert_not_called()


class TestCSPSignalTask(BaseTest):
    @patch("products.signals.backend.api.emit_signal")
    def test_task_calls_emit_signal_with_csp_source(self, mock_emit_signal):
        async def fake_emit(*args, **kwargs):
            return None

        mock_emit_signal.side_effect = fake_emit

        emit_csp_violation_signal_task(
            team_id=self.team.id,
            source_id="csp:abc",
            description="desc",
            extra={"document_url": "https://example.com/page"},
        )

        mock_emit_signal.assert_called_once()
        kwargs = mock_emit_signal.call_args.kwargs
        assert kwargs["source_product"] == "csp_reporting"
        assert kwargs["source_type"] == "violation"
        assert kwargs["source_id"] == "csp:abc"
        assert kwargs["description"] == "desc"
        assert kwargs["team"].id == self.team.id

    @patch("products.signals.backend.api.emit_signal")
    def test_task_swallows_missing_team(self, mock_emit_signal):
        emit_csp_violation_signal_task(
            team_id=999_999_999,
            source_id="csp:abc",
            description="desc",
            extra={},
        )
        mock_emit_signal.assert_not_called()

    @patch("products.signals.backend.api.emit_signal")
    def test_task_swallows_emit_signal_failure(self, mock_emit_signal):
        async def boom(*args, **kwargs):
            raise RuntimeError("temporal unavailable")

        mock_emit_signal.side_effect = boom

        emit_csp_violation_signal_task(
            team_id=self.team.id,
            source_id="csp:abc",
            description="desc",
            extra={},
        )
