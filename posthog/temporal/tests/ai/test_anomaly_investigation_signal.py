from parameterized import parameterized

from posthog.temporal.ai.anomaly_investigation.report import InvestigationReport
from posthog.temporal.ai.anomaly_investigation.workflow import (
    _MAX_DESCRIPTION_CHARS,
    _build_signal_description,
    should_emit_episode_signal,
    should_emit_investigation_signal,
)


class TestBuildSignalDescription:
    def test_long_report_is_truncated_under_cap(self) -> None:
        # A runaway agent summary must not push the description past emit_signal's token limit,
        # which would raise and let the best-effort caller silently drop the signal.
        report = InvestigationReport(
            verdict="true_positive",
            summary="x" * 10000,
            hypotheses=[],
            recommendations=[],
        )

        description = _build_signal_description(
            alert_name="Signups dropped",
            insight_name="Daily signups",
            insight_id="42",
            insight_short_id="abc123",
            report=report,
        )

        assert len(description) <= _MAX_DESCRIPTION_CHARS
        assert description.endswith("…")

    def test_short_report_includes_verdict_and_insight_id(self) -> None:
        report = InvestigationReport(
            verdict="true_positive",
            summary="Signups fell after the deploy.",
            hypotheses=[],
            recommendations=[],
        )

        description = _build_signal_description(
            alert_name="Signups dropped",
            insight_name="Daily signups",
            insight_id="42",
            insight_short_id="abc123",
            report=report,
        )

        assert "verdict: true positive" in description
        assert "id 42" in description


class TestShouldEmitInvestigationSignal:
    # Guards the verdict gate: a regression here floods the Signals inbox with
    # false-positive investigation reports again.
    @parameterized.expand(
        [
            ("true_positive", "notify", True),
            ("true_positive", "suppress", True),
            ("false_positive", "notify", False),
            ("false_positive", "suppress", False),
            ("inconclusive", "notify", True),
            ("inconclusive", "suppress", False),
            ("inconclusive", None, True),
        ]
    )
    def test_gating_by_verdict_and_policy(self, verdict: str, inconclusive_action: str | None, expected: bool) -> None:
        assert should_emit_investigation_signal(verdict, inconclusive_action) is expected


class TestReInvestigationOfAnEpisode:
    def test_description_leads_with_the_verdict_change(self) -> None:
        # The change is why the agent ran again, and it is what groups the update onto
        # the episode's existing report.
        report = InvestigationReport(
            verdict="true_positive",
            summary="The drop is real, the checkout API is erroring.",
            hypotheses=[],
            recommendations=[],
        )

        description = _build_signal_description(
            alert_name="Signups dropped",
            insight_name="Daily signups",
            insight_id="42",
            insight_short_id="abc123",
            report=report,
            previous_verdict="false_positive",
        )

        assert description.startswith("Verdict changed from false positive to true positive")

    @parameterized.expand(
        [
            ("first_investigation", "true_positive", None, True),
            ("verdict_held", "true_positive", "true_positive", False),
            ("verdict_flipped", "true_positive", "false_positive", True),
            ("still_dismissed", "false_positive", "false_positive", False),
            ("flipped_to_dismissed", "false_positive", "true_positive", False),
        ]
    )
    def test_only_a_changed_verdict_reaches_the_inbox_again(
        self, _name: str, verdict: str, previous_verdict: str | None, expected: bool
    ) -> None:
        assert should_emit_episode_signal(verdict, previous_verdict, "notify") is expected
