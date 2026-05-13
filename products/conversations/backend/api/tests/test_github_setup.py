from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership


class TestGithubSetupEndpoints(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.client.force_login(self.user)

        self.integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="12345",
            config={"account": {"name": "org"}},
        )
        self.team.conversations_enabled = True
        self.team.conversations_settings = {
            "github_enabled": True,
            "github_integration_id": self.integration.id,
            "github_repos": ["org/repo"],
        }
        self.team.save()

    @parameterized.expand(
        [
            # (name, settings, expected_connected, expected_integration_present)
            ("connected", None, True, True),
            ("disconnected", {}, False, False),
        ]
    )
    def test_status(self, _name, settings_override, expected_connected, expected_integration_present):
        if settings_override is not None:
            self.team.conversations_settings = settings_override
            self.team.save()

        resp = self.client.get("/api/conversations/v1/github/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is expected_connected
        assert (data["integration"] is not None) == expected_integration_present

    def test_connect_sets_integration(self):
        self.team.conversations_settings = {}
        self.team.save()

        resp = self.client.post(
            "/api/conversations/v1/github/connect",
            {"integration_id": self.integration.id},
            content_type="application/json",
        )
        assert resp.status_code == 200

        self.team.refresh_from_db()
        settings = self.team.conversations_settings
        assert settings["github_enabled"] is True
        assert settings["github_integration_id"] == self.integration.id

    @parameterized.expand(
        [
            ("missing_id", {}, 400),
            ("nonexistent_id", {"integration_id": 99999}, 404),
        ]
    )
    def test_connect_rejects_bad_input(self, _name, payload, expected_status):
        resp = self.client.post(
            "/api/conversations/v1/github/connect",
            payload,
            content_type="application/json",
        )
        assert resp.status_code == expected_status

    def test_disconnect_clears_settings(self):
        resp = self.client.post("/api/conversations/v1/github/disconnect", content_type="application/json")
        assert resp.status_code == 200

        self.team.refresh_from_db()
        settings = self.team.conversations_settings
        assert settings["github_enabled"] is False
        assert "github_integration_id" not in settings
        assert "github_repos" not in settings

    @parameterized.expand(
        [
            ("valid_repos", ["org/repo", "org/other-repo"], 200, ["org/repo", "org/other-repo"]),
            ("filters_invalid", ["valid/repo", "../../etc/passwd"], 200, ["valid/repo"]),
            ("too_many", [f"org/repo-{i}" for i in range(101)], 400, None),
        ]
    )
    def test_select_repos(self, _name, repos, expected_status, expected_repos):
        resp = self.client.post(
            "/api/conversations/v1/github/select-repos",
            {"repos": repos},
            content_type="application/json",
        )
        assert resp.status_code == expected_status
        if expected_repos is not None:
            self.team.refresh_from_db()
            assert self.team.conversations_settings["github_repos"] == expected_repos

    def test_select_repos_requires_connection(self):
        self.team.conversations_settings = {}
        self.team.save()

        resp = self.client.post(
            "/api/conversations/v1/github/select-repos",
            {"repos": ["org/repo"]},
            content_type="application/json",
        )
        assert resp.status_code == 400

    @patch("products.conversations.backend.api.github_setup.create_github_issue")
    def test_create_issue_dispatches_task(self, mock_task):
        mock_task.delay = MagicMock()
        resp = self.client.post(
            "/api/conversations/v1/github/create-issue",
            {"repo": "org/repo", "title": "New bug", "body": "Details"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        mock_task.delay.assert_called_once()
        call_kwargs = mock_task.delay.call_args[1]
        assert call_kwargs["repo"] == "org/repo"
        assert call_kwargs["title"] == "New bug"

    @parameterized.expand(
        [
            ("unmonitored_repo", {"repo": "org/other", "title": "Bug"}, False),
            ("missing_title", {"repo": "org/repo"}, False),
            ("invalid_labels", {"repo": "org/repo", "title": "Bug", "labels": [1, 2, 3]}, False),
            ("path_traversal_repo", {"repo": "../evil/repo", "title": "Bug"}, True),
            ("spaces_in_repo", {"repo": "org/ repo", "title": "Bug"}, True),
            ("no_slash_repo", {"repo": "just-a-name", "title": "Bug"}, True),
        ]
    )
    @patch("products.conversations.backend.api.github_setup.create_github_issue")
    def test_create_issue_rejects_bad_input(self, _name, payload, add_to_allowed, mock_task):
        mock_task.delay = MagicMock()
        if add_to_allowed and "repo" in payload:
            self.team.conversations_settings["github_repos"].append(payload["repo"])
            self.team.save()

        resp = self.client.post(
            "/api/conversations/v1/github/create-issue",
            payload,
            content_type="application/json",
        )
        assert resp.status_code == 400
        mock_task.delay.assert_not_called()
