from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import HealthCheckSignalExtra, SignalRemediation

from posthog.models import Team
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.framework import (
    AlertContent,
    HealthCheck,
    Remediation,
    SignalContent,
    build_signal_extra,
)
from posthog.temporal.health_checks.processing import _process_batch_detection
from posthog.temporal.health_checks.signal_emitter import emit_health_check_signal


class _SignalCheck(HealthCheck):
    # No name/kind -> __init_subclass__ skips auto-registration.
    remediation = Remediation(
        human="Open the health page and set your authorized URLs.",
        agent="Call `project-settings-update` to set app_urls; verify with `project-get`.",
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return AlertContent(title="stub", summary="stub", link="/web/health")

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        return SignalContent(
            description="something is wrong with instrumentation",
            weight=0.7,
            extra=build_signal_extra(issue, title="stub", summary="stub", link="/web/health"),
        )


class _NoSignalCheck(HealthCheck):
    # Inherits the base render_signal -> returns None (opt out).
    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return AlertContent(title="stub", summary="stub", link="/health")


def _make_issue(kind: str = "stub_check", severity: str = "warning") -> HealthIssue:
    return HealthIssue(team_id=42, kind=kind, severity=severity, payload={"detail": "x"}, unique_hash="h")


class TestBaseRenderSignal(SimpleTestCase):
    def test_base_render_signal_returns_none(self):
        assert _NoSignalCheck.render_signal(_make_issue()) is None


class TestBuildSignalExtra(SimpleTestCase):
    def test_extra_satisfies_signal_schema(self):
        # emit_signal validates extra against this variant; if the envelope drifts
        # from the schema, every emit fails validation.
        issue = _make_issue(severity="critical")
        extra = build_signal_extra(issue, title="t", summary="s", link="/web/health")
        HealthCheckSignalExtra.model_validate(extra)
        assert extra["kind"] == "stub_check"
        assert extra["severity"] == "critical"
        assert extra["issue_id"] == str(issue.id)
        assert extra["url"].endswith("/web/health")
        assert "remediation" not in extra


class TestEmitHealthCheckSignal(SimpleTestCase):
    def test_calls_emit_signal_with_weight_and_extra(self):
        emit_mock = AsyncMock()
        team = MagicMock(spec=Team)
        with (
            patch("posthog.temporal.health_checks.signal_emitter._check_class_for_kind", return_value=_SignalCheck),
            patch("products.signals.backend.facade.api.emit_signal", new=emit_mock),
            patch("posthog.temporal.health_checks.signal_emitter.Team") as team_model,
        ):
            team_model.objects.get.return_value = team
            issue = _make_issue()
            ok = emit_health_check_signal(issue)

        assert ok is True
        kwargs = emit_mock.call_args.kwargs
        assert kwargs["source_product"] == "health_checks"
        assert kwargs["source_type"] == "health_issue"
        assert kwargs["source_id"] == str(issue.id)
        assert kwargs["weight"] == 0.7
        assert kwargs["extra"]["kind"] == "stub_check"
        assert kwargs["remediation"] == SignalRemediation(
            human="Open the health page and set your authorized URLs.",
            agent="Call `project-settings-update` to set app_urls; verify with `project-get`.",
        )

    def test_check_without_override_emits_nothing(self):
        emit_mock = AsyncMock()
        with (
            patch("posthog.temporal.health_checks.signal_emitter._check_class_for_kind", return_value=_NoSignalCheck),
            patch("products.signals.backend.facade.api.emit_signal", new=emit_mock),
        ):
            ok = emit_health_check_signal(_make_issue())

        assert ok is False
        emit_mock.assert_not_called()

    def test_unregistered_kind_emits_nothing(self):
        emit_mock = AsyncMock()
        with (
            patch("posthog.temporal.health_checks.signal_emitter._check_class_for_kind", return_value=None),
            patch("products.signals.backend.facade.api.emit_signal", new=emit_mock),
        ):
            ok = emit_health_check_signal(_make_issue(kind="not_in_registry"))

        assert ok is False
        emit_mock.assert_not_called()

    def test_emit_signal_failure_is_swallowed_and_captured(self):
        emit_mock = AsyncMock(side_effect=RuntimeError("temporal down"))
        with (
            patch("posthog.temporal.health_checks.signal_emitter._check_class_for_kind", return_value=_SignalCheck),
            patch("products.signals.backend.facade.api.emit_signal", new=emit_mock),
            patch("posthog.temporal.health_checks.signal_emitter.Team") as team_model,
            patch("posthog.temporal.health_checks.signal_emitter.capture_exception") as capture,
        ):
            team_model.objects.get.return_value = MagicMock(spec=Team)
            ok = emit_health_check_signal(_make_issue())

        assert ok is False
        capture.assert_called_once()


class TestSeamEmitsSignalsOnFiringOnly(SimpleTestCase):
    @parameterized.expand([("dry_run_off", False)])
    def test_signal_emitted_for_newly_active_not_resolved(self, _name: str, dry_run: bool):
        firing = _make_issue(kind="k")
        resolved = _make_issue(kind="k")

        with (
            patch("posthog.temporal.health_checks.processing.upsert_issues_with_deltas", return_value=[firing]),
            patch(
                "posthog.temporal.health_checks.processing.resolve_stale_issues_with_deltas", return_value=[resolved]
            ),
            patch("posthog.temporal.health_checks.processing.emit_health_check_alert"),
            patch("posthog.temporal.health_checks.processing.emit_health_check_signal") as emit_signal,
        ):
            _process_batch_detection([42], "k", lambda team_ids: {}, dry_run=dry_run)

        emit_signal.assert_called_once_with(firing)
