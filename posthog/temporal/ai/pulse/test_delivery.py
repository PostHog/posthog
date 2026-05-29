from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from posthog.models import PulseDigest, PulseFinding, User
from posthog.models.pulse import PulseDigestStatus
from posthog.models.scoping import team_scope
from posthog.temporal.ai.pulse.delivery import _dispatch_pulse_notifications, _persist_findings_sync
from posthog.temporal.ai.pulse.types import EnrichedFinding, MetricDescriptor

from products.notifications.backend.facade.enums import NotificationType, Priority, SourceType, TargetType
from products.notifications.backend.models import NotificationEvent


def _finding() -> EnrichedFinding:
    return EnrichedFinding(
        descriptor=MetricDescriptor(source="top_event", label="Signups", query={}),
        current_value=70.0,
        baseline_value=50.0,
        change_pct=0.4,
        impact=2.83,
        robust_z=3.5,
        narrative="Signups rose 40% this week.",
    )


class TestPulseNotificationFanout(BaseTest):
    def setUp(self):
        super().setUp()
        self.user2 = User.objects.create_and_join(self.organization, "second@test.com", "pw")
        now = timezone.now()
        with team_scope(self.team.id):
            self.digest = PulseDigest.objects.create(
                team=self.team,
                period_start=now - timezone.timedelta(days=7),
                period_end=now,
                status=PulseDigestStatus.GENERATING,
            )

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_kafka")
    def test_one_notification_per_team_member(self, mock_publish, mock_ff):
        _dispatch_pulse_notifications(self.team.id, str(self.digest.id), [_finding()])

        events = list(NotificationEvent.objects.filter(notification_type=NotificationType.PULSE_DIGEST.value))
        # Fan-out is one create_notification per recipient; target_type=USER resolves to that single user.
        assert {e.target_id for e in events} == {str(self.user.id), str(self.user2.id)}
        ev = events[0]
        assert ev.priority == Priority.NORMAL.value
        assert ev.source_type == SourceType.PULSE.value
        assert ev.source_id == str(self.digest.id)
        assert ev.source_url == f"/pulse?digest={self.digest.id}"
        assert ev.target_type == TargetType.USER.value
        assert "Signups" in ev.title

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_kafka")
    def test_idempotent_on_retry(self, mock_publish, mock_ff):
        _dispatch_pulse_notifications(self.team.id, str(self.digest.id), [_finding()])
        first = NotificationEvent.objects.filter(notification_type=NotificationType.PULSE_DIGEST.value).count()

        _dispatch_pulse_notifications(self.team.id, str(self.digest.id), [_finding()])
        second = NotificationEvent.objects.filter(notification_type=NotificationType.PULSE_DIGEST.value).count()

        assert first == 2
        assert second == 2  # no duplicates on a Temporal retry

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_kafka")
    def test_no_findings_dispatches_nothing(self, mock_publish, mock_ff):
        _dispatch_pulse_notifications(self.team.id, str(self.digest.id), [])

        assert NotificationEvent.objects.filter(notification_type=NotificationType.PULSE_DIGEST.value).count() == 0

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_kafka")
    def test_title_summarizes_multiple_findings(self, mock_publish, mock_ff):
        second = _finding()
        second.descriptor = MetricDescriptor(source="top_event", label="Churn", query={})
        _dispatch_pulse_notifications(self.team.id, str(self.digest.id), [_finding(), second])

        ev = NotificationEvent.objects.filter(notification_type=NotificationType.PULSE_DIGEST.value).first()
        assert ev is not None
        assert "Signups" in ev.title
        assert "+1 more" in ev.title

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_kafka")
    def test_persist_marks_digest_delivered_without_channels(self, mock_publish, mock_ff):
        with team_scope(self.team.id):
            PulseFinding.objects.filter(digest=self.digest).delete()
            pairs = _persist_findings_sync(str(self.digest.id), self.team.id, [_finding()])

        self.digest.refresh_from_db()
        assert self.digest.status == PulseDigestStatus.DELIVERED
        assert len(pairs) == 1
        # No channel bookkeeping is read or written anymore.
        assert not hasattr(self.digest, "delivered_to")
