from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.utils import timezone

from structlog.contextvars import merge_contextvars
from structlog.testing import capture_logs

from posthog.dataclasses import frozen
from posthog.models import Integration

from products.customer_analytics.backend.logic.feature_request_github import process_github_issue_update
from products.customer_analytics.backend.models import (
    FeatureRequestGitHubLink,
    FeatureRequestHistory,
    FeatureRequestStatus,
)
from products.customer_analytics.backend.test.factories import (
    create_account,
    create_feature_request,
    create_feature_request_account_link,
    create_feature_request_history,
)


@frozen
class _RequestState:
    version: int
    updated_at: datetime
    updated_by_id: int | None
    history_count: int


class TestFeatureRequestGitHubMetadataOnlySync(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="installation-1",
            config={},
            sensitive_config={},
        )
        self.request = create_feature_request(team_id=self.team.id, status=FeatureRequestStatus.PLANNED)
        self.request.updated_by_id = self.user.id
        self.request.save(update_fields=["updated_by_id"])
        account = create_account(team_id=self.team.id)
        create_feature_request_account_link(team_id=self.team.id, feature_request=self.request, account=account)
        create_feature_request_history(
            team_id=self.team.id,
            feature_request=self.request,
            changed_at=timezone.now(),
            is_initial=True,
        )
        self.link = FeatureRequestGitHubLink.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            feature_request=self.request,
            integration=self.integration,
            sync_enabled_by=self.user,
            installation_id="installation-1",
            repository="posthog/posthog",
            issue_number=42,
            issue_title="Original title",
            issue_state="open",
            github_updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            last_synced_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        self.url = f"/api/projects/{self.team.id}/feature_requests/{self.request.id}/"
        self.flag = patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
        self.flag.start()
        self.addCleanup(self.flag.stop)

    def _request_snapshot(self) -> _RequestState:
        self.request.refresh_from_db()
        return _RequestState(
            version=self.request.version,
            updated_at=self.request.updated_at,
            updated_by_id=self.request.updated_by_id,
            history_count=FeatureRequestHistory.objects.for_team(self.team.id)
            .filter(feature_request=self.request)
            .count(),
        )

    def test_resume_refreshes_newer_title_without_changing_the_request(self) -> None:
        before = self._request_snapshot()
        synced_at = datetime(2026, 1, 3, tzinfo=UTC)
        response = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "number": 42,
                    "title": "Renamed export",
                    "state": "open",
                    "state_reason": None,
                    "updated_at": "2026-01-02T00:00:00Z",
                    "repository_url": "https://api.github.com/repos/PostHog/PostHog",
                    "html_url": "https://github.com/PostHog/PostHog/issues/42",
                }
            ),
        )

        with (
            patch(
                "products.customer_analytics.backend.logic.feature_request_github.GitHubIntegration.api_request",
                return_value=response,
            ),
            patch(
                "products.customer_analytics.backend.logic.feature_request_github.timezone.now", return_value=synced_at
            ),
        ):
            resumed = self.client.post(f"{self.url}resume_github/", {"expected_version": before.version}, format="json")

        self.assertEqual(resumed.status_code, 200)
        self.link.refresh_from_db()
        self.assertEqual(self.link.issue_title, "Renamed export")
        self.assertEqual(self.link.github_updated_at, datetime(2026, 1, 2, tzinfo=UTC))
        self.assertEqual(self.link.last_synced_at, synced_at)
        self.assertEqual(self._request_snapshot(), before)

    def test_worker_refreshes_newer_title_without_changing_the_request(self) -> None:
        before = self._request_snapshot()
        synced_at = datetime(2026, 1, 3, tzinfo=UTC)

        with capture_logs(processors=[merge_contextvars]) as logs:
            with (
                patch(
                    "products.customer_analytics.backend.logic.feature_request_github.posthog_feature_flag_enabled",
                    return_value=True,
                ),
                patch(
                    "products.customer_analytics.backend.logic.feature_request_github.timezone.now",
                    return_value=synced_at,
                ),
                self.captureOnCommitCallbacks(execute=True),
            ):
                process_github_issue_update(
                    installation_id="installation-1",
                    repository="PostHog/PostHog",
                    issue_number=42,
                    issue_title="Renamed export",
                    issue_state="open",
                    issue_state_reason="",
                    github_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
                )

        self.link.refresh_from_db()
        self.assertEqual(self.link.issue_title, "Renamed export")
        self.assertEqual(self.link.github_updated_at, datetime(2026, 1, 2, tzinfo=UTC))
        self.assertEqual(self.link.last_synced_at, synced_at)
        self.assertEqual(self._request_snapshot(), before)
        applied = next(log for log in logs if log["event"] == "feature_request_github_target_applied")
        self.assertFalse(applied["changed"])
