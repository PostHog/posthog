from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from products.customer_analytics.backend.logic.custom_property_source_health import (
    MAX_CONSECUTIVE_SYNC_FAILURES,
    record_sync_failure,
    record_sync_success,
)
from products.customer_analytics.backend.models import CustomPropertySource
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin
from products.customer_analytics.backend.test.factories import create_custom_property_definition

SERVICE = "products.customer_analytics.backend.logic.custom_property_source_health"


@patch(f"{SERVICE}.notify_source_auto_disabled")
class TestCustomPropertySourceHealth(TeamScopedTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan")
        self.source = CustomPropertySource.objects.create(
            team=self.team,
            definition=definition,
            key_column="external_id",
            source_column="plan",
        )

    def _fail(self, *, job_id: str = "job-1", count_failure: bool = True) -> bool:
        with self.captureOnCommitCallbacks(execute=True):
            return record_sync_failure(self.source, error="boom", disable_event_id=job_id, count_failure=count_failure)

    def test_source_stays_enabled_until_the_threshold(self, mock_notify) -> None:
        for _ in range(MAX_CONSECUTIVE_SYNC_FAILURES - 1):
            assert self._fail() is False

        self.source.refresh_from_db()
        assert self.source.is_enabled is True
        mock_notify.assert_not_called()

    def test_the_threshold_failure_disables_and_tells_the_owner_once(self, mock_notify) -> None:
        self.source.consecutive_failures = MAX_CONSECUTIVE_SYNC_FAILURES - 1
        self.source.save()

        assert self._fail() is True

        self.source.refresh_from_db()
        assert self.source.is_enabled is False
        mock_notify.assert_called_once_with(team_id=self.team.id, source_id=self.source.id, disable_event_id="job-1")

    def test_a_failure_on_an_already_disabled_source_tells_nobody_again(self, mock_notify) -> None:
        self.source.consecutive_failures = MAX_CONSECUTIVE_SYNC_FAILURES
        self.source.is_enabled = False
        self.source.save()

        assert self._fail(job_id="job-2") is False
        mock_notify.assert_not_called()

    def test_an_uncounted_failure_does_not_move_the_streak(self, mock_notify) -> None:
        self.source.consecutive_failures = MAX_CONSECUTIVE_SYNC_FAILURES - 1
        self.source.save()

        assert self._fail(count_failure=False) is False

        self.source.refresh_from_db()
        assert self.source.consecutive_failures == MAX_CONSECUTIVE_SYNC_FAILURES - 1
        assert self.source.is_enabled is True
        mock_notify.assert_not_called()

    def test_success_clears_the_streak_and_the_error(self, _mock_notify) -> None:
        self.source.consecutive_failures = 3
        self.source.last_sync_error = "boom"
        self.source.save()

        finished_at = timezone.now()
        record_sync_success(self.source, finished_at=finished_at)

        stored = CustomPropertySource.objects.for_team(self.team.id).get(id=self.source.id)
        assert stored.consecutive_failures == 0
        assert stored.last_sync_error is None
        assert stored.last_synced_at == finished_at

    def test_a_later_disablement_after_re_enabling_tells_the_owner_again(self, mock_notify) -> None:
        self.source.consecutive_failures = MAX_CONSECUTIVE_SYNC_FAILURES - 1
        self.source.save()
        self._fail(job_id="job-1")

        self.source.is_enabled = True
        self.source.consecutive_failures = MAX_CONSECUTIVE_SYNC_FAILURES - 1
        self.source.save()
        self._fail(job_id="job-2")

        assert [call.kwargs["disable_event_id"] for call in mock_notify.call_args_list] == ["job-1", "job-2"]
