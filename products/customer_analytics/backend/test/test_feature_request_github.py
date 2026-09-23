import hmac
import json
import hashlib
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.db import transaction
from django.test import SimpleTestCase

import structlog
from celery import current_app
from parameterized import parameterized
from rest_framework import status
from structlog.contextvars import bound_contextvars, clear_contextvars, merge_contextvars
from structlog.testing import capture_logs

from posthog.constants import AvailableFeature
from posthog.ingress.contracts import WebhookDelivery
from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.models import Integration, OrganizationMembership, Team, User
from posthog.models.organization import Organization

from products.access_control.backend.models import AccessControl
from products.customer_analytics.backend.logic.feature_request_github import (
    FeatureRequestConflictError,
    FeatureRequestValidationError,
    _parse_issue_url,
    process_github_issue_update,
)
from products.customer_analytics.backend.models import (
    FeatureRequestGitHubLink,
    FeatureRequestHistory,
    FeatureRequestHistorySource,
    FeatureRequestStatus,
)
from products.customer_analytics.backend.test.factories import (
    create_account,
    create_feature_request,
    create_feature_request_account_link,
)
from products.customer_analytics.backend.webhook_consumers import _run_github_issue_delivery

if TYPE_CHECKING:
    from products.customer_analytics.backend.models import FeatureRequest


class TestFeatureRequestGitHubIssueUrl(SimpleTestCase):
    def test_normalizes_issue_comment_url_and_rejects_non_issue_paths(self) -> None:
        self.assertEqual(
            _parse_issue_url("https://github.com/PostHog/PostHog/issues/42#issuecomment-1"),
            ("posthog/posthog", 42),
        )
        for url in (
            "http://github.com/posthog/posthog/issues/42",
            "https://github.com/posthog/posthog/pull/42",
            "https://github.com/posthog/posthog/issues/42?state=open",
            "https://github.com.evil.example/posthog/posthog/issues/42",
        ):
            with self.assertRaises(FeatureRequestValidationError):
                _parse_issue_url(url)

    def test_issue_delivery_queues_only_issue_metadata(self) -> None:
        clear_contextvars()
        self.addCleanup(clear_contextvars)
        task = current_app.tasks["customer_analytics.process_feature_request_github_issue"]
        with (
            patch.object(task, "delay", return_value=Mock(id="task-1")) as delay,
            patch(
                "products.customer_analytics.backend.webhook_consumers.logger",
                structlog.get_logger("test.feature_request_github.delivery"),
            ),
            capture_logs(processors=[merge_contextvars]) as logs,
        ):
            _run_github_issue_delivery(
                WebhookDelivery(
                    provider="github",
                    app="posthog",
                    delivery_id="delivery-1",
                    event_type="issues",
                    payload={
                        "action": "closed",
                        "installation": {"id": 123},
                        "repository": {"full_name": "PostHog/PostHog"},
                        "issue": {
                            "number": 42,
                            "title": "Export CSV",
                            "state": "closed",
                            "state_reason": "completed",
                            "updated_at": "2026-01-01T00:00:00Z",
                            "body": "This must never enter the worker payload.",
                        },
                    },
                    received_at=datetime(2026, 1, 1, tzinfo=UTC),
                    context={},
                )
            )

        delay.assert_called_once_with(
            installation_id="123",
            repository="posthog/posthog",
            issue_number=42,
            issue_title="Export CSV",
            issue_state="closed",
            issue_state_reason="completed",
            github_updated_at="2026-01-01T00:00:00+00:00",
            github_delivery_id="delivery-1",
            github_received_at="2026-01-01T00:00:00+00:00",
        )
        queued = [log for log in logs if log["event"] == "feature_request_github_delivery_queued"][-1]
        self.assertEqual(
            {key: queued[key] for key in ("github_delivery_id", "task_id", "sync_attempt")},
            {"github_delivery_id": "delivery-1", "task_id": "task-1", "sync_attempt": 0},
        )
        self.assertNotIn("Export CSV", repr(queued))
        self.assertNotIn("This must never enter the worker payload.", repr(queued))
        self.assertNotIn("PostHog/PostHog", repr(queued))

    @parameterized.expand(
        (
            ("boolean_issue_number", {"number": True}),
            ("boolean_installation_id", {"installation_id": True}),
            ("naive_timestamp", {"updated_at": "2026-01-01T00:00:00"}),
            ("unknown_closed_reason", {"state_reason": "reopened"}),
        )
    )
    @patch("products.customer_analytics.backend.facade.api.process_feature_request_github_delivery")
    def test_issue_delivery_ignores_invalid_worker_metadata(
        self, _name: str, invalid_field: dict[str, object], process_delivery: Mock
    ) -> None:
        issue: dict[str, object] = {
            "number": 42,
            "title": "Export CSV",
            "state": "closed",
            "state_reason": "completed",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        installation: dict[str, object] = {"id": 123}
        if "installation_id" in invalid_field:
            installation["id"] = invalid_field["installation_id"]
        else:
            issue.update(invalid_field)
        _run_github_issue_delivery(
            WebhookDelivery(
                provider="github",
                app="posthog",
                delivery_id="delivery-1",
                event_type="issues",
                payload={
                    "action": "closed",
                    "installation": installation,
                    "repository": {"full_name": "PostHog/PostHog"},
                    "issue": issue,
                },
                received_at=datetime(2026, 1, 1, tzinfo=UTC),
                context={},
            )
        )

        process_delivery.assert_not_called()


class TestFeatureRequestGitHubIngress(SimpleTestCase):
    def setUp(self) -> None:
        reset_consumer_registry()
        cache.clear()
        self.addCleanup(reset_consumer_registry)
        self.addCleanup(cache.clear)

    @staticmethod
    def _signature(body: bytes, secret: str) -> str:
        return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    @patch("posthog.models.integration.github.GitHubIntegration.api_request")
    @patch("products.workflows.backend.facade.api.accept_github_event")
    @patch("products.tasks.backend.facade.api.accept_github_event_for_loops")
    @patch("products.conversations.backend.facade.api.accept_github_event")
    @patch("products.customer_analytics.backend.facade.api.process_feature_request_github_delivery")
    @patch("posthog.ingress.github.provider.get_instance_setting", return_value="test-webhook-secret")
    def test_signed_issue_delivery_enqueues_only_feature_request_work(
        self,
        _get_secret: Mock,
        process_delivery: Mock,
        conversations: Mock,
        loops: Mock,
        workflows: Mock,
        api_request: Mock,
    ) -> None:
        body = json.dumps(
            {
                "action": "closed",
                "installation": {"id": 123},
                "repository": {"full_name": "PostHog/PostHog"},
                "issue": {
                    "number": 42,
                    "title": "Export CSV",
                    "state": "closed",
                    "state_reason": "completed",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
            }
        ).encode()

        response = self.client.post(
            "/webhooks/github/",
            data=body,
            content_type="application/json",
            headers={
                "X-Hub-Signature-256": self._signature(body, "test-webhook-secret"),
                "X-GitHub-Event": "issues",
                "X-GitHub-Delivery": "delivery-1",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        process_delivery.assert_called_once_with(
            installation_id="123",
            repository="posthog/posthog",
            issue_number=42,
            issue_title="Export CSV",
            issue_state="closed",
            issue_state_reason="completed",
            github_updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            github_delivery_id="delivery-1",
            github_received_at=process_delivery.call_args.kwargs["github_received_at"],
        )
        self.assertIsNotNone(datetime.fromisoformat(process_delivery.call_args.kwargs["github_received_at"]))
        conversations.assert_called_once()
        loops.assert_called_once()
        workflows.assert_called_once()
        api_request.assert_not_called()


class TestFeatureRequestGitHubAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.account = create_account(team_id=self.team.id)
        self.request = create_feature_request(team_id=self.team.id, status=FeatureRequestStatus.PLANNED)
        create_feature_request_account_link(team_id=self.team.id, feature_request=self.request, account=self.account)
        self.integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="installation-1",
            config={},
            sensitive_config={},
        )
        self.url = f"/api/projects/{self.team.id}/feature_requests/{self.request.id}/"
        self.flag = patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
        self.flag.start()
        self.addCleanup(self.flag.stop)
        self.api_request = patch(
            "products.customer_analytics.backend.logic.feature_request_github.GitHubIntegration.api_request",
            return_value=self._github_response(),
        )
        self.mock_api_request = self.api_request.start()
        self.addCleanup(self.api_request.stop)

    @staticmethod
    def _github_response(
        *,
        title: str = "Export CSV",
        state: str = "open",
        state_reason: str | None = None,
        updated_at: str = "2026-01-01T00:00:00Z",
    ) -> Mock:
        return Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "number": 42,
                    "title": title,
                    "state": state,
                    "state_reason": state_reason,
                    "updated_at": updated_at,
                    "repository_url": "https://api.github.com/repos/PostHog/PostHog",
                    "html_url": "https://github.com/PostHog/PostHog/issues/42",
                }
            ),
        )

    def _link(self, version: int | None = None) -> Any:
        return self.client.post(
            f"{self.url}link_github/",
            {
                "integration_id": self.integration.id,
                "issue_url": "https://github.com/PostHog/PostHog/issues/42",
                "expected_version": version or self.request.version,
            },
            format="json",
        )

    def test_link_pause_resume_and_unlink_preserve_the_public_link_contract(self) -> None:
        linked = self._link()

        self.assertEqual(linked.status_code, status.HTTP_200_OK)
        self.assertEqual(
            linked.json()["github_link"],
            {
                "id": linked.json()["github_link"]["id"],
                "issue_url": "https://github.com/posthog/posthog/issues/42",
                "repository": "posthog/posthog",
                "issue_number": 42,
                "issue_title": "Export CSV",
                "issue_state": "open",
                "sync_enabled": True,
                "last_synced_at": linked.json()["github_link"]["last_synced_at"],
            },
        )
        paused = self.client.post(
            f"{self.url}pause_github/", {"expected_version": linked.json()["version"]}, format="json"
        )
        resumed = self.client.post(
            f"{self.url}resume_github/", {"expected_version": paused.json()["version"]}, format="json"
        )
        unlinked = self.client.post(
            f"{self.url}unlink_github/", {"expected_version": resumed.json()["version"]}, format="json"
        )

        self.assertEqual(paused.status_code, status.HTTP_200_OK)
        self.assertFalse(paused.json()["github_link"]["sync_enabled"])
        self.assertEqual(resumed.status_code, status.HTTP_200_OK)
        self.assertTrue(resumed.json()["github_link"]["sync_enabled"])
        self.assertEqual(unlinked.status_code, status.HTTP_200_OK)
        self.assertIsNone(unlinked.json()["github_link"])
        self.assertEqual(
            FeatureRequestHistory.objects.for_team(self.team.id)
            .filter(feature_request=self.request, source=FeatureRequestHistorySource.GITHUB)
            .count(),
            4,
        )

    def test_stale_link_version_does_not_fetch_or_modify_the_existing_link(self) -> None:
        response = self._link(version=self.request.version + 1)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.mock_api_request.assert_not_called()
        self.assertFalse(FeatureRequestGitHubLink.objects.for_team(self.team.id).exists())

    def test_duplicate_issue_url_does_not_fetch_or_modify_the_existing_link(self) -> None:
        linked = self._link()
        self.mock_api_request.reset_mock()

        duplicate = self._link(version=linked.json()["version"])

        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)
        self.mock_api_request.assert_not_called()
        link = FeatureRequestGitHubLink.objects.for_team(self.team.id).get()
        self.assertEqual(link.issue_title, "Export CSV")
        self.assertTrue(link.sync_enabled)

    def test_unknown_closed_reason_is_rejected_without_creating_a_link(self) -> None:
        self.mock_api_request.return_value = self._github_response(state="closed", state_reason="reopened")

        response = self._link()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(FeatureRequestGitHubLink.objects.for_team(self.team.id).exists())

    @parameterized.expand((("deleted",), ("unavailable",)))
    def test_unavailable_integrations_are_rejected_without_fetching(self, state: str) -> None:
        if state == "deleted":
            self.integration.delete()
        else:
            self.integration.config = {"installation_unavailable_since": 1}
            self.integration.save(update_fields=["config"])

        response = self._link()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.mock_api_request.assert_not_called()
        self.assertFalse(FeatureRequestGitHubLink.objects.for_team(self.team.id).exists())

    def test_failed_refetch_keeps_the_existing_link_unchanged(self) -> None:
        linked = self._link()
        paused = self.client.post(
            f"{self.url}pause_github/", {"expected_version": linked.json()["version"]}, format="json"
        )
        self.mock_api_request.return_value = Mock(
            status_code=500,
            text="private upstream error",
            title="private issue title",
            body="private issue body",
        )
        clear_contextvars()

        with (
            patch(
                "products.customer_analytics.backend.logic.feature_request_github.logger",
                structlog.get_logger("test.feature_request_github.fetch_failure"),
            ),
            capture_logs(processors=[merge_contextvars]) as logs,
        ):
            response = self.client.post(
                f"{self.url}resume_github/", {"expected_version": paused.json()["version"]}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        link = FeatureRequestGitHubLink.objects.for_team(self.team.id).get()
        self.assertEqual(link.repository, "posthog/posthog")
        self.assertEqual(link.issue_number, 42)
        self.assertFalse(link.sync_enabled)
        failed_fetch = [log for log in logs if log["event"] == "feature_request_github_issue_fetch_failed"][-1]
        self.assertEqual(failed_fetch["feature_request_id"], str(self.request.id))
        self.assertIsInstance(failed_fetch["action"], str)
        self.assertEqual(failed_fetch["status_code"], 500)
        for private_value in ("private issue title", "private issue body", "private upstream error"):
            self.assertNotIn(private_value, repr(failed_fetch))

    def test_concurrent_request_change_while_linking_does_not_create_a_link(self) -> None:
        def change_request_during_fetch(*args: object, **kwargs: object) -> Mock:
            self.request.version += 1
            self.request.save(update_fields=["version"])
            return self._github_response()

        self.mock_api_request.side_effect = change_request_during_fetch

        response = self._link()

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertFalse(FeatureRequestGitHubLink.objects.for_team(self.team.id).exists())

    def test_concurrent_request_change_while_resuming_keeps_sync_paused(self) -> None:
        linked = self._link()
        paused = self.client.post(
            f"{self.url}pause_github/", {"expected_version": linked.json()["version"]}, format="json"
        )

        def change_request_during_fetch(*args: object, **kwargs: object) -> Mock:
            self.request.refresh_from_db()
            self.request.version += 1
            self.request.save(update_fields=["version"])
            return self._github_response()

        self.mock_api_request.side_effect = change_request_during_fetch
        resumed = self.client.post(
            f"{self.url}resume_github/", {"expected_version": paused.json()["version"]}, format="json"
        )

        self.assertEqual(resumed.status_code, status.HTTP_409_CONFLICT)
        self.assertFalse(FeatureRequestGitHubLink.objects.for_team(self.team.id).get().sync_enabled)

    @parameterized.expand(
        (mode, state) for mode in ("manual", "manual_after_pause", "pause") for state in ("open", "closed")
    )
    def test_pause_and_resume_preserve_status_ownership(self, mode: str, state: str) -> None:
        self.mock_api_request.return_value = self._github_response(state="closed", state_reason="completed")
        linked = self._link()
        self.assertEqual(linked.status_code, 200)
        version = linked.json()["version"]
        if mode != "manual":
            paused = self.client.post(f"{self.url}pause_github/", {"expected_version": version}, format="json")
            self.assertEqual(paused.status_code, 200)
            version = paused.json()["version"]
        if mode.startswith("manual"):
            changed = self.client.patch(
                self.url, {"expected_version": version, "request_status": "requested"}, format="json"
            )
            self.assertEqual(changed.status_code, 200)
            self.assertFalse(changed.json()["github_link"]["sync_enabled"])
            version = changed.json()["version"]
        restored_status = "requested" if mode.startswith("manual") else "planned"
        with patch(
            "products.customer_analytics.backend.logic.feature_request_github.posthog_feature_flag_enabled",
            autospec=True,
            return_value=True,
        ):
            process_github_issue_update(
                installation_id="installation-1",
                repository="posthog/posthog",
                issue_number=42,
                issue_title="GitHub title",
                issue_state="open",
                issue_state_reason="",
                github_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
            )
        self.request.refresh_from_db()
        self.assertEqual(self.request.version, version)
        self.mock_api_request.return_value = self._github_response(
            state=state,
            state_reason="not_planned" if state == "closed" else None,
            updated_at="2026-01-02T00:00:00Z",
        )
        resumed = self.client.post(f"{self.url}resume_github/", {"expected_version": version}, format="json")
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.json()["version"], version + 1)
        self.assertEqual(resumed.json()["request_status"], "wont_fix" if state == "closed" else restored_status)
        self.assertTrue(resumed.json()["github_link"]["sync_enabled"])
        self.assertEqual(resumed.json()["title"], self.request.title)
        self.assertEqual(resumed.json()["description"], self.request.description)
        if state == "closed":
            history = self.client.get(f"{self.url}history/").json()
            self.assertTrue(
                any(change["field"] == "status" and change["after"] == "wont_fix" for change in history[0]["changes"])
            )
            with patch(
                "products.customer_analytics.backend.logic.feature_request_github.posthog_feature_flag_enabled",
                autospec=True,
                return_value=True,
            ):
                process_github_issue_update(
                    installation_id="installation-1",
                    repository="posthog/posthog",
                    issue_number=42,
                    issue_title="GitHub title",
                    issue_state="open",
                    issue_state_reason="",
                    github_updated_at=datetime(2026, 1, 3, tzinfo=UTC),
                )
            self.request.refresh_from_db()
            self.assertEqual(self.request.status, restored_status)

    @parameterized.expand(("link_github", "pause_github", "resume_github", "unlink_github"))
    def test_account_viewer_cannot_change_github_or_trigger_a_fetch(self, action: str) -> None:
        linked = self._link()
        self.assertEqual(linked.status_code, 200)
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        reader = User.objects.create_and_join(self.organization, "github-reader@example.com", "testtest")
        membership = OrganizationMembership.objects.get(user=reader, organization=self.organization)
        AccessControl.objects.create(
            team=self.team, resource="customer_analytics", access_level="editor", organization_member=membership
        )
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(self.account.id),
            access_level="viewer",
            organization_member=membership,
        )
        self.client.force_login(reader)
        self.mock_api_request.reset_mock()
        response = self.client.post(
            f"{self.url}{action}/",
            {
                "expected_version": linked.json()["version"],
                "integration_id": self.integration.id,
                "issue_url": "https://github.com/posthog/posthog/issues/42",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.mock_api_request.assert_not_called()

    @parameterized.expand(("link_github", "resume_github"))
    def test_denied_integration_access_rejects_link_and_resume_without_fetching(self, action: str) -> None:
        if action == "resume_github":
            linked = self._link()
            paused = self.client.post(
                f"{self.url}pause_github/", {"expected_version": linked.json()["version"]}, format="json"
            )
            expected_version = paused.json()["version"]
        else:
            expected_version = self.request.version
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        reader = User.objects.create_and_join(self.organization, "integration-reader@example.com", "testtest")
        membership = OrganizationMembership.objects.get(user=reader, organization=self.organization)
        AccessControl.objects.create(
            team=self.team, resource="customer_analytics", access_level="editor", organization_member=membership
        )
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(self.account.id),
            access_level="editor",
            organization_member=membership,
        )
        AccessControl.objects.create(
            team=self.team, resource="integration", access_level="none", organization_member=membership
        )
        self.client.force_login(reader)
        self.mock_api_request.reset_mock()

        response = self.client.post(
            f"{self.url}{action}/",
            {
                "expected_version": expected_version,
                "integration_id": self.integration.id,
                "issue_url": "https://github.com/posthog/posthog/issues/42",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.mock_api_request.assert_not_called()

    def test_another_projects_integration_cannot_be_used(self) -> None:
        other_organization = Organization.objects.create(name="Other organization")
        other_team = Team.objects.create(organization=other_organization, name="Other project")
        self.integration.team = other_team
        self.integration.save(update_fields=["team"])
        response = self._link()
        self.assertEqual(response.status_code, 400)
        self.mock_api_request.assert_not_called()
        self.assertFalse(FeatureRequestGitHubLink.objects.for_team(self.team.id).exists())


class TestFeatureRequestGitHubWorker(APIBaseTest):
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
        )
        self.flag = patch(
            "products.customer_analytics.backend.logic.feature_request_github.posthog_feature_flag_enabled",
            return_value=True,
        )
        self.flag.start()
        self.addCleanup(self.flag.stop)

    @staticmethod
    def _log(logs: Sequence[Mapping[str, object]], event: str) -> Mapping[str, object]:
        return next(log for log in logs if log["event"] == event)

    def _deliver(
        self,
        *,
        issue_number: int = 42,
        title: str = "Updated title",
        state: str = "closed",
        reason: str = "completed",
        updated_at: datetime = datetime(2026, 1, 1, tzinfo=UTC),
    ) -> None:
        process_github_issue_update(
            installation_id="installation-1",
            repository="PostHog/PostHog",
            issue_number=issue_number,
            issue_title=title,
            issue_state=state,
            issue_state_reason=reason,
            github_updated_at=updated_at,
        )

    @parameterized.expand(
        (
            ("completed", FeatureRequestStatus.COMPLETED),
            ("not_planned", FeatureRequestStatus.WONT_FIX),
            ("", FeatureRequestStatus.COMPLETED),
        )
    )
    def test_closed_issue_maps_known_and_legacy_reasons_to_request_status(
        self, reason: str, expected_status: str
    ) -> None:
        self._deliver(reason=reason)

        self.request.refresh_from_db()
        self.link.refresh_from_db()
        self.assertEqual(self.request.status, expected_status)
        self.assertEqual(self.link.status_before_github_close, FeatureRequestStatus.PLANNED)
        history = (
            FeatureRequestHistory.objects.for_team(self.team.id)
            .filter(feature_request=self.request, source=FeatureRequestHistorySource.GITHUB)
            .get()
        )
        self.assertEqual(history.source, FeatureRequestHistorySource.GITHUB)
        self.assertEqual(history.changes, [{"field": "status", "before": "planned", "after": expected_status}])

    def test_reopen_restores_the_baseline_without_replacing_it_on_repeated_close(self) -> None:
        self._deliver(title="Closed once")
        self._deliver(title="Closed twice", updated_at=datetime(2026, 1, 2, tzinfo=UTC))
        self._deliver(state="open", reason="", updated_at=datetime(2026, 1, 3, tzinfo=UTC))

        self.request.refresh_from_db()
        self.link.refresh_from_db()
        self.assertEqual(self.request.status, FeatureRequestStatus.PLANNED)
        self.assertIsNone(self.link.status_before_github_close)
        self.assertEqual(self.link.issue_title, "Updated title")

    @parameterized.expand((("disabled", "sync_enabled"), ("archived", "archived_at"), ("disconnected", "integration")))
    def test_worker_ignores_links_that_cannot_sync(self, condition: str, field: str) -> None:
        if field == "sync_enabled":
            self.link.sync_enabled = False
            self.link.save(update_fields=[field])
        elif field == "archived_at":
            self.request.archived_at = datetime(2026, 1, 1, tzinfo=UTC)
            self.request.save(update_fields=[field])
        else:
            self.link.integration = None
            self.link.save(update_fields=[field])

        self._deliver()

        self.request.refresh_from_db()
        self.link.refresh_from_db()
        self.assertEqual(self.request.status, FeatureRequestStatus.PLANNED)
        self.assertEqual(self.link.issue_title, "Original title")

    def test_worker_logs_applied_target_after_commit_with_delivery_correlation(self) -> None:
        with capture_logs(processors=[merge_contextvars]) as logs:
            with bound_contextvars(
                github_delivery_id="delivery-1",
                task_id="task-1",
                sync_attempt=0,
                github_received_at="2026-01-01T00:00:00+00:00",
            ):
                with self.captureOnCommitCallbacks(execute=True):
                    self._deliver()
                    self.assertFalse(any(log["event"] == "feature_request_github_target_applied" for log in logs))

        applied = self._log(logs, "feature_request_github_target_applied")
        self.assertEqual(
            {key: applied[key] for key in ("github_delivery_id", "task_id", "sync_attempt", "installation_id")},
            {
                "github_delivery_id": "delivery-1",
                "task_id": "task-1",
                "sync_attempt": 0,
                "installation_id": "installation-1",
            },
        )
        self.assertEqual(
            {key: applied[key] for key in ("status_before", "status_after", "changed")},
            {"status_before": "planned", "status_after": "completed", "changed": True},
        )
        summary = self._log(logs, "feature_request_github_delivery_summary")
        self.assertNotIn("feature_request_id", summary)
        self.assertNotIn("github_link_id", summary)
        self.assertEqual(
            {key: summary[key] for key in ("outcome", "matched", "applied", "skipped", "conflicted", "failed")},
            {"outcome": "success", "matched": 1, "applied": 1, "skipped": 0, "conflicted": 0, "failed": 0},
        )

    @parameterized.expand(
        (
            ("flag_disabled",),
            ("user_missing",),
            ("unavailable",),
            ("stale",),
            ("duplicate",),
            ("no_matches",),
        )
    )
    def test_worker_logs_skipped_target_reasons_and_summary_counts(self, reason: str) -> None:
        if reason == "user_missing":
            self.link.sync_enabled_by = None
            self.link.save(update_fields=["sync_enabled_by"])
        elif reason == "unavailable":
            self.link.integration = None
            self.link.save(update_fields=["integration"])
        elif reason in {"stale", "duplicate"}:
            self.link.github_updated_at = datetime(2026, 1, 2, tzinfo=UTC)
            self.link.issue_state = "closed"
            self.link.issue_state_reason = "completed"
            self.link.save(update_fields=["github_updated_at", "issue_state", "issue_state_reason"])

        with capture_logs(processors=[merge_contextvars]) as logs:
            if reason == "flag_disabled":
                with patch(
                    "products.customer_analytics.backend.logic.feature_request_github.posthog_feature_flag_enabled",
                    return_value=False,
                ):
                    self._deliver()
            else:
                self._deliver(
                    issue_number=43 if reason == "no_matches" else 42,
                    updated_at=datetime(2026, 1, 1, tzinfo=UTC)
                    if reason == "stale"
                    else datetime(2026, 1, 2, tzinfo=UTC),
                )

        summary = self._log(logs, "feature_request_github_delivery_summary")
        self.assertEqual(summary["matched"], 0 if reason == "no_matches" else 1)
        self.assertEqual(summary["applied"], 0)
        self.assertEqual(summary["skipped"], 0 if reason == "no_matches" else 1)
        if reason != "no_matches":
            skipped = self._log(logs, "feature_request_github_target_skipped")
            self.assertEqual(skipped["reason"], reason)

    def test_worker_logs_no_applied_target_when_transaction_rolls_back(self) -> None:
        original_on_commit = transaction.on_commit

        def schedule_then_fail(callback: Callable[[], None]) -> None:
            original_on_commit(callback)
            raise RuntimeError("rollback")

        with capture_logs(processors=[merge_contextvars]) as logs:
            with patch(
                "products.customer_analytics.backend.logic.feature_request_github.transaction.on_commit",
                side_effect=schedule_then_fail,
            ):
                with self.assertRaisesRegex(RuntimeError, "rollback"):
                    self._deliver()

        self.assertFalse(any(log["event"] == "feature_request_github_target_applied" for log in logs))

    def test_shared_installation_fans_out_only_to_matching_issue_links(self) -> None:
        second_team = Team.objects.create(organization=self.organization, name="Second project")
        second_integration = Integration.objects.create(
            team=second_team,
            kind="github",
            integration_id="installation-1",
            config={},
            sensitive_config={},
        )
        second_request = create_feature_request(team_id=second_team.id, status=FeatureRequestStatus.REQUESTED)
        FeatureRequestGitHubLink.objects.for_team(second_team.id).create(
            team_id=second_team.id,
            feature_request=second_request,
            integration=second_integration,
            sync_enabled_by=self.user,
            installation_id="installation-1",
            repository="posthog/posthog",
            issue_number=42,
            issue_title="Original title",
            issue_state="open",
        )
        unrelated = create_feature_request(team_id=second_team.id, status=FeatureRequestStatus.PLANNED)
        FeatureRequestGitHubLink.objects.for_team(second_team.id).create(
            team_id=second_team.id,
            feature_request=unrelated,
            integration=second_integration,
            installation_id="installation-1",
            repository="posthog/posthog",
            issue_number=43,
            issue_title="Unrelated",
            issue_state="open",
        )

        self._deliver()

        self.request.refresh_from_db()
        second_request.refresh_from_db()
        unrelated.refresh_from_db()
        self.assertEqual(self.request.status, FeatureRequestStatus.COMPLETED)
        self.assertEqual(second_request.status, FeatureRequestStatus.COMPLETED)
        self.assertEqual(unrelated.status, FeatureRequestStatus.PLANNED)

    def test_conflicted_link_does_not_block_other_links_in_the_delivery(self) -> None:
        second_user = User.objects.create_and_join(self.organization, "second-github-sync-user@example.com", "testtest")
        second_request = create_feature_request(team_id=self.team.id, status=FeatureRequestStatus.PLANNED)
        second_link = FeatureRequestGitHubLink.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            feature_request=second_request,
            integration=self.integration,
            sync_enabled_by=second_user,
            installation_id="installation-1",
            repository="posthog/posthog",
            issue_number=42,
            issue_title="Original title",
            issue_state="open",
        )
        requests_by_distinct_id = {
            str(self.user.distinct_id): self.request,
            str(second_user.distinct_id): second_request,
        }
        conflicted_request: FeatureRequest | None = None

        def change_first_target_before_locking(_flag: str, distinct_id: str, **_kwargs: object) -> bool:
            nonlocal conflicted_request
            if conflicted_request is None:
                conflicted_request = requests_by_distinct_id[distinct_id]
                conflicted_request.version += 1
                conflicted_request.save(update_fields=["version"])
            return True

        with capture_logs(processors=[merge_contextvars]) as logs:
            with patch(
                "products.customer_analytics.backend.logic.feature_request_github.posthog_feature_flag_enabled",
                side_effect=change_first_target_before_locking,
            ):
                with self.captureOnCommitCallbacks(execute=True):
                    with self.assertRaises(FeatureRequestConflictError):
                        self._deliver()

        self.assertEqual(self._log(logs, "feature_request_github_target_conflicted")["reason"], "version_conflict")
        self.assertEqual(self._log(logs, "feature_request_github_target_applied")["changed"], True)
        summary = self._log(logs, "feature_request_github_delivery_summary")
        self.assertEqual(
            {
                key: summary[key]
                for key in ("outcome", "matched", "applied", "skipped", "conflicted", "failed", "error_type")
            },
            {
                "outcome": "failure",
                "matched": 2,
                "applied": 1,
                "skipped": 0,
                "conflicted": 1,
                "failed": 0,
                "error_type": "FeatureRequestConflictError",
            },
        )

        if conflicted_request is None:
            self.fail("Expected a target to conflict.")
        other_request = second_request if conflicted_request.id == self.request.id else self.request
        conflicted_link = self.link if conflicted_request.id == self.request.id else second_link
        other_link = second_link if conflicted_request.id == self.request.id else self.link
        conflicted_request.refresh_from_db()
        other_request.refresh_from_db()
        conflicted_link.refresh_from_db()
        other_link.refresh_from_db()
        self.assertEqual(conflicted_request.status, FeatureRequestStatus.PLANNED)
        self.assertEqual(conflicted_link.issue_title, "Original title")
        self.assertEqual(other_request.status, FeatureRequestStatus.COMPLETED)
        self.assertEqual(other_link.issue_title, "Updated title")

    def test_duplicate_or_old_delivery_creates_no_history_or_version_change(self) -> None:
        timestamp = datetime(2026, 1, 2, tzinfo=UTC)
        self._deliver(updated_at=timestamp)
        self.request.refresh_from_db()
        version = self.request.version
        history_count = FeatureRequestHistory.objects.for_team(self.team.id).count()

        self._deliver(title="Duplicate", updated_at=timestamp)
        self._deliver(title="Old", updated_at=datetime(2026, 1, 1, tzinfo=UTC))

        self.request.refresh_from_db()
        self.link.refresh_from_db()
        self.assertEqual(self.request.version, version)
        self.assertEqual(FeatureRequestHistory.objects.for_team(self.team.id).count(), history_count)
        self.assertEqual(self.link.issue_title, "Updated title")

    @patch("products.customer_analytics.backend.logic.feature_request_github.GitHubIntegration.api_request")
    def test_conflicting_delivery_at_the_same_timestamp_refetches_the_current_issue(self, api_request: Mock) -> None:
        timestamp = datetime(2026, 1, 2, tzinfo=UTC)
        self.link.github_updated_at = timestamp
        self.link.save(update_fields=["github_updated_at"])
        api_request.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "number": 42,
                    "title": "Current title",
                    "state": "closed",
                    "state_reason": "completed",
                    "updated_at": "2026-01-02T00:00:00Z",
                    "repository_url": "https://api.github.com/repos/PostHog/PostHog",
                    "html_url": "https://github.com/PostHog/PostHog/issues/42",
                }
            ),
        )

        self._deliver(state="closed", updated_at=timestamp)

        self.request.refresh_from_db()
        self.link.refresh_from_db()
        self.assertEqual(self.request.status, FeatureRequestStatus.COMPLETED)
        self.assertEqual(self.link.issue_title, "Current title")
        api_request.assert_called_once()
