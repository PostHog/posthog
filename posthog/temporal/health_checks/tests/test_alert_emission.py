from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.alerts import EVENT_FIRING, EVENT_RESOLVED, emit_health_check_alert
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck


class _StubCheck(HealthCheck):
    # No name/kind class attributes -> __init_subclass__ skips auto-registration.
    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return AlertContent(title="stub title", summary=f"stub for {issue.kind}", link="/health/stub")


class _BadCheck(HealthCheck):
    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        raise ValueError("boom")


def _make_issue(kind: str = "stub_check", severity: str = "warning") -> HealthIssue:
    return HealthIssue(team_id=42, kind=kind, severity=severity, payload={"detail": "x"}, unique_hash="h")


class TestEmitHealthCheckAlert(SimpleTestCase):
    @patch("posthog.temporal.health_checks.alerts._check_class_for_kind", return_value=_StubCheck)
    @patch("posthog.temporal.health_checks.alerts.produce_internal_event")
    def test_firing_emits_event_with_envelope(self, produce, _lookup):
        issue = _make_issue()
        fired = emit_health_check_alert(issue, status="firing")
        self.assertTrue(fired)
        produce.assert_called_once()
        kwargs = produce.call_args.kwargs
        self.assertEqual(kwargs["team_id"], 42)
        event = kwargs["event"]
        self.assertEqual(event.event, EVENT_FIRING)
        self.assertEqual(event.distinct_id, "team_42")
        self.assertEqual(event.properties["kind"], "stub_check")
        self.assertEqual(event.properties["severity"], "warning")
        self.assertEqual(event.properties["title"], "stub title")
        self.assertEqual(event.properties["summary"], "stub for stub_check")
        self.assertEqual(event.properties["link"], "/health/stub")
        self.assertEqual(event.properties["payload"], {"detail": "x"})

    @patch("posthog.temporal.health_checks.alerts._check_class_for_kind", return_value=_StubCheck)
    @patch("posthog.temporal.health_checks.alerts.produce_internal_event")
    def test_resolved_emits_resolved_event(self, produce, _lookup):
        emit_health_check_alert(_make_issue(), status="resolved")
        self.assertEqual(produce.call_args.kwargs["event"].event, EVENT_RESOLVED)

    @patch("posthog.temporal.health_checks.alerts._check_class_for_kind", return_value=None)
    @patch("posthog.temporal.health_checks.alerts.produce_internal_event")
    def test_unregistered_kind_falls_back_to_generic_content(self, produce, _lookup):
        emit_health_check_alert(_make_issue(kind="not_in_registry"), status="firing")
        props = produce.call_args.kwargs["event"].properties
        # Generic fallback: title == kind, link defaults to /health
        self.assertEqual(props["title"], "not_in_registry")
        self.assertEqual(props["link"], "/health")

    @parameterized.expand(
        [
            ("produce_fails", _StubCheck, RuntimeError("kafka down"), True),
            ("render_fails", _BadCheck, None, False),
        ]
    )
    def test_failure_is_swallowed_and_captured(
        self,
        _name: str,
        check_cls: type[HealthCheck],
        produce_side_effect: Exception | None,
        expects_produce_call: bool,
    ) -> None:
        with (
            patch("posthog.temporal.health_checks.alerts._check_class_for_kind", return_value=check_cls),
            patch(
                "posthog.temporal.health_checks.alerts.produce_internal_event",
                side_effect=produce_side_effect,
            ) as produce,
            patch("posthog.temporal.health_checks.alerts.capture_exception") as capture,
        ):
            fired = emit_health_check_alert(_make_issue(), status="firing")
            self.assertFalse(fired)
            if expects_produce_call:
                produce.assert_called_once()
            else:
                produce.assert_not_called()
            capture.assert_called_once()
