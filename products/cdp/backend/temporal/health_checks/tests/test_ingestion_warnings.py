from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.health_issue import HealthIssue

from products.cdp.backend.temporal.health_checks.ingestion_warnings import (
    IngestionWarningsCheck,
    _humanize_warning_type,
)


def _issue(warning_type: str, category: str, severity: str, affected_count: int = 12) -> HealthIssue:
    health_severity = {
        "error": HealthIssue.Severity.CRITICAL,
        "warning": HealthIssue.Severity.WARNING,
        "info": HealthIssue.Severity.INFO,
    }[severity]
    return HealthIssue(
        team_id=1,
        kind="ingestion_warning",
        severity=health_severity,
        payload={
            "warning_type": warning_type,
            "category": category,
            "severity": severity,
            "affected_count": affected_count,
        },
    )


class TestHumanizeWarningType(SimpleTestCase):
    @parameterized.expand(
        [
            ("high_volume_distinct_id", "High volume distinct ID"),
            ("duplicate_event_uuid", "Duplicate event UUID"),
            ("invalid_ai_event", "Invalid AI event"),
            ("message_size_too_large", "Message size too large"),
        ]
    )
    def test_reads_as_a_label_not_a_raw_type(self, warning_type: str, expected: str):
        assert _humanize_warning_type(warning_type) == expected


class TestIngestionWarningsSignal(SimpleTestCase):
    def test_quota_warning_says_nothing_was_dropped(self):
        signal = IngestionWarningsCheck.render_signal(_issue("high_volume_distinct_id", "quota", "warning"))
        assert signal is not None
        # The customer-facing bug: quota warnings must never claim data was lost.
        assert "nothing was dropped" in signal.description
        assert "incomplete" not in signal.description
        assert "high-volume distinct IDs" in signal.description
        # Label is humanized, raw snake_case type is gone from the copy.
        assert "high_volume_distinct_id" not in signal.description
        assert "High volume distinct ID" in signal.description

    def test_error_warning_reports_dropped_and_incomplete_data(self):
        signal = IngestionWarningsCheck.render_signal(_issue("message_size_too_large", "size", "error"))
        assert signal is not None
        assert "were dropped" in signal.description
        assert "incomplete" in signal.description

    def test_warning_severity_reports_changed_not_dropped_data(self):
        signal = IngestionWarningsCheck.render_signal(_issue("distinct_id_truncated", "event", "warning"))
        assert signal is not None
        assert "may be" in signal.description
        assert "were dropped" not in signal.description

    def test_info_warning_does_not_claim_every_event_was_dropped(self):
        # replay_lib_version_too_old and client_ingestion_warning drop nothing, so the info
        # copy must not tell users every info warning intentionally dropped their events.
        signal = IngestionWarningsCheck.render_signal(_issue("replay_lib_version_too_old", "replay", "info"))
        assert signal is not None
        assert "informational" in signal.description
        assert "drop nothing" in signal.description
        assert "incomplete" not in signal.description

    def test_alert_summary_uses_human_label(self):
        alert = IngestionWarningsCheck.render_alert(_issue("high_volume_distinct_id", "quota", "warning"))
        assert alert.summary == "High volume distinct ID fired 12 times"
