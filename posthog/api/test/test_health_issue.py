import json
from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.models.health_issue import HealthIssue
from posthog.models.team import Team
from posthog.redis import get_client

from products.growth.backend.constants import github_sdk_versions_key


class TestHealthIssueAPI(APIBaseTest):
    def _url(self, path: str = "", team_id: int | None = None) -> str:
        return f"/api/environments/{team_id or self.team.id}/health_issues{path}"

    def _reset_refresh_throttle(self, team_id: int | None = None) -> None:
        key = f"throttle_health_issue_refresh_team_{team_id or self.team.id}"
        cache.delete(key)
        self.addCleanup(cache.delete, key)

    def _create_issue(self, **kwargs) -> HealthIssue:
        defaults = {
            "team": self.team,
            "kind": "sdk_outdated",
            "severity": HealthIssue.Severity.WARNING,
            "payload": {"sdk_version": "1.0.0"},
            "unique_hash": "default_hash",
        }
        defaults.update(kwargs)
        return HealthIssue.objects.create(**defaults)

    def test_list_returns_issues_ordered_by_severity(self):
        info = self._create_issue(severity=HealthIssue.Severity.INFO, unique_hash="h1")
        critical = self._create_issue(severity=HealthIssue.Severity.CRITICAL, unique_hash="h2")
        warning = self._create_issue(severity=HealthIssue.Severity.WARNING, unique_hash="h3")

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.json()["results"]
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["id"], str(critical.id))
        self.assertEqual(results[1]["id"], str(warning.id))
        self.assertEqual(results[2]["id"], str(info.id))

    @parameterized.expand(
        [
            ("status", "active", 2),
            ("status", "resolved", 1),
            ("severity", "critical", 1),
            ("severity", "warning", 2),
            ("kind", "sdk_outdated", 2),
            ("kind", "missing_events", 1),
            ("dismissed", "true", 1),
            ("dismissed", "false", 2),
        ]
    )
    def test_filter_by_param(self, filter_name, filter_value, expected_count):
        self._create_issue(severity=HealthIssue.Severity.CRITICAL, kind="sdk_outdated", unique_hash="h1")
        self._create_issue(severity=HealthIssue.Severity.WARNING, kind="sdk_outdated", unique_hash="h2")
        resolved = self._create_issue(severity=HealthIssue.Severity.WARNING, kind="missing_events", unique_hash="h3")
        resolved.resolve()
        resolved.dismissed = True
        resolved.save(update_fields=["dismissed"])

        response = self.client.get(self._url(), {filter_name: filter_value})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), expected_count)

    @parameterized.expand(
        [
            ("status", "invalid_status"),
            ("status", "dismissed"),
            ("severity", "mind_boggling"),
        ]
    )
    def test_invalid_filter_returns_400(self, filter_name, filter_value):
        response = self.client.get(self._url(), {filter_name: filter_value})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_team_scoping(self):
        self._create_issue(unique_hash="h1")

        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        HealthIssue.objects.create(
            team=other_team,
            kind="other_issue",
            severity=HealthIssue.Severity.CRITICAL,
            payload={},
            unique_hash="other_hash",
        )

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["kind"], "sdk_outdated")

    def test_retrieve_single_issue(self):
        issue = self._create_issue()

        response = self.client.get(self._url(f"/{issue.id}"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["id"], str(issue.id))
        self.assertEqual(data["kind"], "sdk_outdated")
        self.assertEqual(data["severity"], "warning")
        self.assertEqual(data["status"], "active")
        self.assertIn("payload", data)
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)
        self.assertNotIn("unique_hash", data)
        self.assertNotIn("team", data)

    def test_retrieve_enriches_with_rendered_explanation(self):
        issue = self._create_issue(
            kind="sdk_outdated",
            payload={"sdk_name": "posthog-python", "latest_version": "3.0.0", "reason": "posthog-python is behind"},
        )

        response = self.client.get(self._url(f"/{issue.id}"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["title"], "posthog-python SDK is outdated")
        self.assertEqual(data["summary"], "posthog-python is behind")
        self.assertEqual(data["link"], "/health/sdk-health")
        # remediation is the static, kind-level constant (not interpolated per issue),
        # split into human/agent halves and normalized by cleandoc (no leading indent).
        self.assertTrue(data["remediation"]["human"].startswith("Open the SDK Health page"))
        self.assertIn("bump the PostHog SDK dependency", data["remediation"]["agent"])

    def test_retrieve_unknown_kind_falls_back_to_generic_envelope(self):
        issue = self._create_issue(kind="not_a_registered_check", payload={})

        response = self.client.get(self._url(f"/{issue.id}"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["title"], "not_a_registered_check")
        self.assertEqual(data["link"], "/health")
        self.assertIsNone(data["remediation"])

    def test_retrieve_remediation_has_human_and_agent_halves(self):
        issue = self._create_issue(kind="reverse_proxy", payload={"reason": "No reverse proxy"})

        response = self.client.get(self._url(f"/{issue.id}"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        remediation = response.json()["remediation"]
        self.assertEqual(set(remediation.keys()), {"human", "agent"})
        self.assertTrue(remediation["human"])
        self.assertTrue(remediation["agent"])

    def test_list_omits_rendered_explanation_fields(self):
        self._create_issue()

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        result = response.json()["results"][0]
        for field in ("title", "summary", "link", "remediation"):
            self.assertNotIn(field, result)

    def test_retrieve_nonexistent_returns_404(self):
        response = self.client.get(self._url("/00000000-0000-0000-0000-000000000000"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_resolve_action(self):
        issue = self._create_issue()

        response = self.client.post(self._url(f"/{issue.id}/resolve"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "resolved")

        issue.refresh_from_db()
        self.assertEqual(issue.status, HealthIssue.Status.RESOLVED)

    def test_patch_dismiss(self):
        issue = self._create_issue()

        response = self.client.patch(self._url(f"/{issue.id}"), {"dismissed": True}, content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["dismissed"])

        issue.refresh_from_db()
        self.assertTrue(issue.dismissed)
        self.assertEqual(issue.status, HealthIssue.Status.ACTIVE)

    def test_patch_undismiss(self):
        issue = self._create_issue(dismissed=True)

        response = self.client.patch(self._url(f"/{issue.id}"), {"dismissed": False}, content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["dismissed"])

        issue.refresh_from_db()
        self.assertFalse(issue.dismissed)

    def test_patch_dismiss_resolved_issue(self):
        issue = self._create_issue()
        issue.resolve()

        response = self.client.patch(self._url(f"/{issue.id}"), {"dismissed": True}, content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["dismissed"])
        self.assertEqual(response.json()["status"], "resolved")

    @parameterized.expand(
        [
            ("id", "00000000-0000-0000-0000-000000000000"),
            ("kind", "other_kind"),
            ("severity", "critical"),
            ("status", "resolved"),
            ("payload", {"sdk_version": "2.0.0"}),
            ("created_at", "20256-01-01T00:00:00Z"),
            ("updated_at", "2026-01-01T00:00:00Z"),
            ("resolved_at", "2026-01-01T00:00:00Z"),
        ]
    )
    def test_patch_read_only_field_returns_400(self, field, value):
        issue = self._create_issue()

        response = self.client.patch(self._url(f"/{issue.id}"), {field: value}, content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(field, response.json()["attr"])

    def test_resolve_sets_resolved_at(self):
        issue = self._create_issue()

        self.client.post(self._url(f"/{issue.id}/resolve"))
        issue.refresh_from_db()
        self.assertIsNotNone(issue.resolved_at)

    def test_summary_excludes_resolved_and_dismissed(self):
        self._create_issue(severity=HealthIssue.Severity.CRITICAL, kind="sdk_outdated", unique_hash="h1")
        self._create_issue(severity=HealthIssue.Severity.WARNING, kind="missing_events", unique_hash="h2")
        self._create_issue(severity=HealthIssue.Severity.WARNING, kind="sdk_outdated", unique_hash="h3")
        resolved = self._create_issue(severity=HealthIssue.Severity.CRITICAL, kind="resolved_kind", unique_hash="h4")
        resolved.resolve()
        self._create_issue(
            severity=HealthIssue.Severity.WARNING, kind="dismissed_kind", unique_hash="h5", dismissed=True
        )

        response = self.client.get(self._url("/summary"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["by_severity"], {"critical": 1, "warning": 2})
        self.assertEqual(data["by_kind"], {"sdk_outdated": 2, "missing_events": 1})

    def test_summary_empty(self):
        response = self.client.get(self._url("/summary"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["by_severity"], {})
        self.assertEqual(data["by_kind"], {})

    def test_sdk_issue_visible_even_when_latest_release_is_fresh(self):
        # A fresh upstream release (<7 days old) must not hide sdk_outdated issues — fast-releasing
        # SDKs like posthog-python and posthog-js always have a recent release, so any blanket
        # exclusion keyed on release freshness blacks out their issues permanently. The Redis seed
        # below sets up exactly that condition; the endpoints must ignore it, so don't remove it
        # as unused setup.
        key = github_sdk_versions_key("posthog-python")
        release_date = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        get_client().set(key, json.dumps({"latestVersion": "7.18.3", "releaseDates": {"7.18.3": release_date}}))
        self.addCleanup(get_client().delete, key)

        issue = self._create_issue(
            severity=HealthIssue.Severity.CRITICAL,
            payload={"sdk_name": "posthog-python", "current_version": "7.14.1", "latest_version": "7.18.3"},
            unique_hash="fresh_release",
        )

        list_response = self.client.get(self._url(), {"status": "active", "dismissed": "false"})
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual([result["id"] for result in list_response.json()["results"]], [str(issue.id)])

        summary_response = self.client.get(self._url("/summary"))
        self.assertEqual(summary_response.status_code, status.HTTP_200_OK)
        summary = summary_response.json()
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["by_kind"], {"sdk_outdated": 1})

    def test_resolve_already_resolved_returns_400(self):
        issue = self._create_issue(status=HealthIssue.Status.RESOLVED)

        response = self.client.post(self._url(f"/{issue.id}/resolve"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("posthog.tasks.health_checks.evaluate_health_check_for_team.delay")
    def test_refresh_schedules_a_task_per_registered_kind(self, mock_delay):
        self._reset_refresh_throttle()

        response = self.client.post(self._url("/refresh"))
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        data = response.json()
        self.assertGreater(mock_delay.call_count, 0)
        self.assertEqual(len(data["scheduled_kinds"]), mock_delay.call_count)
        self.assertEqual(data["team_id"], self.team.id)
        self.assertEqual(data["kinds_failed"], [])
        self.assertEqual(set(data["scheduled_kinds"]), {call.kwargs["kind"] for call in mock_delay.call_args_list})
        for call in mock_delay.call_args_list:
            self.assertEqual(call.kwargs["team_id"], self.team.id)

    @patch("posthog.tasks.health_checks.evaluate_health_check_for_team.delay")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_refresh_is_throttled_per_team_after_one_call(self, _enabled, _delay):
        self._reset_refresh_throttle()

        first = self.client.post(self._url("/refresh"))
        self.assertEqual(first.status_code, status.HTTP_202_ACCEPTED)

        second = self.client.post(self._url("/refresh"))
        self.assertEqual(second.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn("Retry-After", second.headers)

    @patch("posthog.tasks.health_checks.evaluate_health_check_for_team.delay")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_refresh_throttle_is_per_team_not_global(self, _enabled, _delay):
        other = Team.objects.create(organization=self.organization, name="Other")
        self._reset_refresh_throttle()
        self._reset_refresh_throttle(team_id=other.id)

        response_a = self.client.post(self._url("/refresh"))
        self.assertEqual(response_a.status_code, status.HTTP_202_ACCEPTED)

        response_b = self.client.post(self._url("/refresh", team_id=other.id))
        self.assertEqual(response_b.status_code, status.HTTP_202_ACCEPTED)

    @patch("posthog.tasks.health_checks.evaluate_health_check_for_team.delay", side_effect=Exception("broker down"))
    def test_refresh_handles_partial_broker_failure(self, _delay):
        self._reset_refresh_throttle()

        response = self.client.post(self._url("/refresh"))
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        data = response.json()
        self.assertEqual(data["scheduled_kinds"], [])
        self.assertGreater(len(data["kinds_failed"]), 0)

    @parameterized.expand(
        [
            ("POST", ""),
            ("PUT", "/00000000-0000-0000-0000-000000000000"),
            ("DELETE", "/00000000-0000-0000-0000-000000000000"),
        ]
    )
    def test_forbidden_methods(self, method, path):
        response = getattr(self.client, method.lower())(self._url(path))
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
