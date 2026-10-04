from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

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
from posthog.temporal.health_checks.signal_emitter import emit_health_check_signals

from products.signals.backend.contracts import HealthCheckSignalExtra, SignalRemediation
from products.signals.backend.enums import ReportPriority


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

    def test_payload_lists_and_strings_are_bounded(self):
        # An unbounded check payload (e.g. one entry per distinct $lib_version) must not flow
        # verbatim into the signal's extra, which the research agent renders into LLM context.
        issue = HealthIssue(
            team_id=42,
            kind="stub_check",
            severity="warning",
            payload={"usage": [f"1.{n}.0" for n in range(100)], "note": "x" * 1000},
            unique_hash="h",
        )
        extra = build_signal_extra(issue, title="t", summary="s", link="/web/health")
        HealthCheckSignalExtra.model_validate(extra)
        bounded_usage = extra["payload"]["usage"]
        assert len(bounded_usage) == 21  # 20 items + one "+N more" marker
        assert "more" in bounded_usage[-1]
        assert extra["payload"]["note"].endswith("… (truncated)")


def _patch_in_bulk(team_model: MagicMock, teams_by_id: dict[int, Team]) -> None:
    # Mirror `Team.objects.select_related("organization").in_bulk([...])`.
    team_model.objects.select_related.return_value.in_bulk.return_value = teams_by_id


class TestEmitHealthCheckSignals(SimpleTestCase):
    def test_calls_emit_signal_with_weight_and_extra(self):
        emit_mock = AsyncMock()
        team = MagicMock(spec=Team)
        with (
            patch("posthog.temporal.health_checks.signal_emitter._check_class_for_kind", return_value=_SignalCheck),
            patch("products.signals.backend.facade.api.emit_signal", new=emit_mock),
            patch("posthog.temporal.health_checks.signal_emitter.Team") as team_model,
        ):
            issue = _make_issue()
            _patch_in_bulk(team_model, {issue.team_id: team})
            queued = emit_health_check_signals([issue])

        assert queued == 1
        kwargs = emit_mock.call_args.kwargs
        assert kwargs["team"] is team
        assert kwargs["source_product"] == "health_checks"
        assert kwargs["source_type"] == "health_issue"
        assert kwargs["source_id"] == str(issue.id)
        assert kwargs["weight"] == 0.7
        assert kwargs["extra"]["kind"] == "stub_check"
        assert kwargs["remediation"] == SignalRemediation(
            human="Open the health page and set your authorized URLs.",
            agent="Call `project-settings-update` to set app_urls; verify with `project-get`.",
            priority=ReportPriority.P2,  # derived from the issue's "warning" severity
        )

    def test_emits_for_every_issue_in_the_batch(self):
        emit_mock = AsyncMock()
        with (
            patch("posthog.temporal.health_checks.signal_emitter._check_class_for_kind", return_value=_SignalCheck),
            patch("products.signals.backend.facade.api.emit_signal", new=emit_mock),
            patch("posthog.temporal.health_checks.signal_emitter.Team") as team_model,
        ):
            issues = [_make_issue(), _make_issue()]
            _patch_in_bulk(team_model, {issues[0].team_id: MagicMock(spec=Team)})
            queued = emit_health_check_signals(issues)

        assert queued == 2
        assert emit_mock.await_count == 2

    def test_empty_batch_emits_nothing(self):
        emit_mock = AsyncMock()
        with (
            patch("products.signals.backend.facade.api.emit_signal", new=emit_mock),
            patch("posthog.temporal.health_checks.signal_emitter.Team") as team_model,
        ):
            queued = emit_health_check_signals([])

        assert queued == 0
        emit_mock.assert_not_called()
        team_model.objects.select_related.assert_not_called()

    def test_check_without_override_emits_nothing(self):
        emit_mock = AsyncMock()
        with (
            patch("posthog.temporal.health_checks.signal_emitter._check_class_for_kind", return_value=_NoSignalCheck),
            patch("products.signals.backend.facade.api.emit_signal", new=emit_mock),
        ):
            queued = emit_health_check_signals([_make_issue()])

        assert queued == 0
        emit_mock.assert_not_called()

    def test_unregistered_kind_emits_nothing(self):
        emit_mock = AsyncMock()
        with (
            patch("posthog.temporal.health_checks.signal_emitter._check_class_for_kind", return_value=None),
            patch("products.signals.backend.facade.api.emit_signal", new=emit_mock),
        ):
            queued = emit_health_check_signals([_make_issue(kind="not_in_registry")])

        assert queued == 0
        emit_mock.assert_not_called()

    def test_emit_signal_failure_is_swallowed_and_captured(self):
        emit_mock = AsyncMock(side_effect=RuntimeError("temporal down"))
        with (
            patch("posthog.temporal.health_checks.signal_emitter._check_class_for_kind", return_value=_SignalCheck),
            patch("products.signals.backend.facade.api.emit_signal", new=emit_mock),
            patch("posthog.temporal.health_checks.signal_emitter.Team") as team_model,
            patch("posthog.temporal.health_checks.signal_emitter.capture_exception") as capture,
        ):
            issue = _make_issue()
            _patch_in_bulk(team_model, {issue.team_id: MagicMock(spec=Team)})
            queued = emit_health_check_signals([issue])

        assert queued == 0
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
            patch("posthog.temporal.health_checks.processing.emit_health_check_signals") as emit_signals,
        ):
            _process_batch_detection([42], "k", lambda team_ids: {}, dry_run=dry_run)

        emit_signals.assert_called_once_with([firing])
