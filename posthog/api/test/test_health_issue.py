from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.models.health_issue import HealthIssue
from posthog.models.team import Team


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
        assert response.status_code == status.HTTP_200_OK

        results = response.json()["results"]
        assert len(results) == 3
        assert results[0]["id"] == str(critical.id)
        assert results[1]["id"] == str(warning.id)
        assert results[2]["id"] == str(info.id)

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
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == expected_count

    @parameterized.expand(
        [
            ("status", "invalid_status"),
            ("status", "dismissed"),
            ("severity", "mind_boggling"),
        ]
    )
    def test_invalid_filter_returns_400(self, filter_name, filter_value):
        response = self.client.get(self._url(), {filter_name: filter_value})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

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
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["kind"] == "sdk_outdated"

    def test_retrieve_single_issue(self):
        issue = self._create_issue()

        response = self.client.get(self._url(f"/{issue.id}"))
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["id"] == str(issue.id)
        assert data["kind"] == "sdk_outdated"
        assert data["severity"] == "warning"
        assert data["status"] == "active"
        assert "payload" in data
        assert "created_at" in data
        assert "updated_at" in data
        assert "unique_hash" not in data
        assert "team" not in data

    def test_retrieve_nonexistent_returns_404(self):
        response = self.client.get(self._url("/00000000-0000-0000-0000-000000000000"))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_resolve_action(self):
        issue = self._create_issue()

        response = self.client.post(self._url(f"/{issue.id}/resolve"))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "resolved"

        issue.refresh_from_db()
        assert issue.status == HealthIssue.Status.RESOLVED

    def test_patch_dismiss(self):
        issue = self._create_issue()

        response = self.client.patch(self._url(f"/{issue.id}"), {"dismissed": True}, content_type="application/json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["dismissed"]

        issue.refresh_from_db()
        assert issue.dismissed
        assert issue.status == HealthIssue.Status.ACTIVE

    def test_patch_undismiss(self):
        issue = self._create_issue(dismissed=True)

        response = self.client.patch(self._url(f"/{issue.id}"), {"dismissed": False}, content_type="application/json")
        assert response.status_code == status.HTTP_200_OK
        assert not response.json()["dismissed"]

        issue.refresh_from_db()
        assert not issue.dismissed

    def test_patch_dismiss_resolved_issue(self):
        issue = self._create_issue()
        issue.resolve()

        response = self.client.patch(self._url(f"/{issue.id}"), {"dismissed": True}, content_type="application/json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["dismissed"]
        assert response.json()["status"] == "resolved"

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
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert field in response.json()["attr"]

    def test_resolve_sets_resolved_at(self):
        issue = self._create_issue()

        self.client.post(self._url(f"/{issue.id}/resolve"))
        issue.refresh_from_db()
        assert issue.resolved_at is not None

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
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["total"] == 3
        assert data["by_severity"] == {"critical": 1, "warning": 2}
        assert data["by_kind"] == {"sdk_outdated": 2, "missing_events": 1}

    def test_summary_empty(self):
        response = self.client.get(self._url("/summary"))
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["total"] == 0
        assert data["by_severity"] == {}
        assert data["by_kind"] == {}

    def test_resolve_already_resolved_returns_400(self):
        issue = self._create_issue(status=HealthIssue.Status.RESOLVED)

        response = self.client.post(self._url(f"/{issue.id}/resolve"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("posthog.tasks.health_checks.evaluate_health_check_for_team.delay")
    def test_refresh_schedules_a_task_per_registered_kind(self, mock_delay):
        self._reset_refresh_throttle()

        response = self.client.post(self._url("/refresh"))
        assert response.status_code == status.HTTP_202_ACCEPTED

        data = response.json()
        assert mock_delay.call_count > 0
        assert len(data["scheduled_kinds"]) == mock_delay.call_count
        assert data["team_id"] == self.team.id
        assert data["kinds_failed"] == []
        assert set(data["scheduled_kinds"]) == {call.kwargs["kind"] for call in mock_delay.call_args_list}
        for call in mock_delay.call_args_list:
            assert call.kwargs["team_id"] == self.team.id

    @patch("posthog.tasks.health_checks.evaluate_health_check_for_team.delay")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_refresh_is_throttled_per_team_after_one_call(self, _enabled, _delay):
        self._reset_refresh_throttle()

        first = self.client.post(self._url("/refresh"))
        assert first.status_code == status.HTTP_202_ACCEPTED

        second = self.client.post(self._url("/refresh"))
        assert second.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "Retry-After" in second.headers

    @patch("posthog.tasks.health_checks.evaluate_health_check_for_team.delay")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_refresh_throttle_is_per_team_not_global(self, _enabled, _delay):
        other = Team.objects.create(organization=self.organization, name="Other")
        self._reset_refresh_throttle()
        self._reset_refresh_throttle(team_id=other.id)

        response_a = self.client.post(self._url("/refresh"))
        assert response_a.status_code == status.HTTP_202_ACCEPTED

        response_b = self.client.post(self._url("/refresh", team_id=other.id))
        assert response_b.status_code == status.HTTP_202_ACCEPTED

    @patch("posthog.tasks.health_checks.evaluate_health_check_for_team.delay", side_effect=Exception("broker down"))
    def test_refresh_handles_partial_broker_failure(self, _delay):
        self._reset_refresh_throttle()

        response = self.client.post(self._url("/refresh"))
        assert response.status_code == status.HTTP_202_ACCEPTED

        data = response.json()
        assert data["scheduled_kinds"] == []
        assert len(data["kinds_failed"]) > 0

    @parameterized.expand(
        [
            ("POST", ""),
            ("PUT", "/00000000-0000-0000-0000-000000000000"),
            ("DELETE", "/00000000-0000-0000-0000-000000000000"),
        ]
    )
    def test_forbidden_methods(self, method, path):
        response = getattr(self.client, method.lower())(self._url(path))
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
