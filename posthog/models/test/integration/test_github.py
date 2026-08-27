"""Tests for the GitHub App integration."""

import time
from datetime import UTC, datetime, timedelta
from typing import Optional

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, call, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone

import requests
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.egress.github.transport import (
    GitHubEgressBudgetExhausted,
    GitHubRateLimitError,
    raise_if_github_rate_limited,
)
from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import (
    GITHUB_BRANCH_CACHE_TTL_SECONDS,
    GITHUB_REPOSITORY_CACHE_TTL_SECONDS,
    GitHubIntegrationBase,
)
from posthog.models.integration import (
    GitHubInstallationAccessFetchError,
    GitHubIntegration,
    GitHubIntegrationError,
    Integration,
    invalidate_github_repository_caches_for_installation,
)


class TestExtractFailingChecks(SimpleTestCase):
    @parameterized.expand(
        [
            ("failure", "FAILURE", True),
            ("timed_out", "TIMED_OUT", True),
            ("action_required", "ACTION_REQUIRED", True),
            ("startup_failure", "STARTUP_FAILURE", True),
            ("cancelled", "CANCELLED", True),
            ("stale", "STALE", True),
            ("success", "SUCCESS", False),
            ("neutral", "NEUTRAL", False),
            ("skipped", "SKIPPED", False),
        ]
    )
    def test_check_run_is_reported_only_when_its_conclusion_blocks_merge(self, _name, conclusion, expected_reported):
        rollup = {
            "contexts": {
                "nodes": [
                    {
                        "__typename": "CheckRun",
                        "conclusion": conclusion,
                        "name": "unit tests",
                        "checkSuite": {"workflowRun": {"workflow": {"name": "CI"}}},
                        "detailsUrl": "https://ci/1",
                    }
                ]
            }
        }

        failing = GitHubIntegrationBase._extract_failing_checks(rollup)

        assert (failing == [{"key": "CI/unit tests", "details_url": "https://ci/1"}]) is expected_reported


class TestGitHubIntegrationModel(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def create_integration(self, config: Optional[dict] = None, sensitive_config: Optional[dict] = None) -> Integration:
        _config = {"expires_at": 3600}
        _sensitive_config = {"token": "REFRESH"}
        _config.update(config or {})
        _sensitive_config.update(sensitive_config or {})

        # Mirror production (integration_from_installation_id): the model integration_id field holds the
        # GitHub App installation id, which is what egress telemetry keys its gauges on.
        return Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id=(config or {}).get("installation_id"),
            config=_config,
            sensitive_config=_sensitive_config,
        )

    def mock_github_client_request(
        self,
        status_code=201,
        token="ACCESS_TOKEN",
        repository_selection="all",
        expires_in_hours=1,
        error_text=None,
        permissions=None,
    ):
        def _client_request(endpoint, method="GET"):
            mock_response = MagicMock()
            if method == "POST":
                mock_response.status_code = status_code
                dt = datetime.now(UTC) + timedelta(hours=expires_in_hours)
                iso_time = dt.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"

                if status_code == 201:
                    mock_response.json.return_value = {
                        "token": token,
                        "repository_selection": repository_selection,
                        "expires_at": iso_time,
                        **({"permissions": permissions} if permissions is not None else {}),
                    }
                else:
                    mock_response.text = error_text or "error"
                    mock_response.json.return_value = {}
            else:
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "account": {"type": "Organization", "login": "PostHog"},
                    **({"permissions": permissions} if permissions is not None else {}),
                }
            return mock_response

        return _client_request

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_mint_scoped_installation_token_marks_uninstalled_installation(self, mock_client_request):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "expires_in": 3600, "refreshed_at": 1704110400},
            {"access_token": "FULL_TOKEN"},
        )
        mock_response = MagicMock(status_code=404, text="Not Found")
        mock_response.json.return_value = {"message": "Not Found"}
        mock_client_request.return_value = mock_response

        github = GitHubIntegration(integration)
        with pytest.raises(GitHubIntegrationError):
            github.mint_scoped_installation_token({"contents": "read"})

        # Without the permanently-gone marker, every scheduled run re-mints a dead installation
        # forever — the marker is what lets callers skip it until the customer reconnects.
        integration.refresh_from_db()
        assert GitHubIntegration(integration).installation_unavailable() is True
        assert "expires_in" not in integration.config

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_mint_scoped_installation_token_downscopes_without_persisting(self, mock_client_request):
        integration = self.create_integration({"installation_id": "INSTALL"}, {"access_token": "FULL_TOKEN"})
        mock_response = MagicMock(status_code=201)
        mock_response.json.return_value = {"token": "SCOPED_TOKEN", "expires_at": "2024-01-01T13:00:00Z"}
        mock_client_request.return_value = mock_response

        token = GitHubIntegration(integration).mint_scoped_installation_token({"contents": "read"})

        assert token == "SCOPED_TOKEN"
        # Without the permissions body the mint returns a FULL-permission token — a silent
        # privilege escalation for every read-only sandbox.
        assert mock_client_request.call_args.kwargs["json_body"] == {"permissions": {"contents": "read"}}
        # The scoped token must never clobber the shared full-permission credential other flows read.
        integration.refresh_from_db()
        assert integration.sensitive_config == {"token": "REFRESH", "access_token": "FULL_TOKEN"}

    def test_get_diff_compares_branch_tips(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        mock_response = MagicMock(status_code=200, text="diff --git a b")
        with patch.object(github, "api_request", return_value=mock_response) as mock_get:
            result = github.get_diff("PostHog/posthog", target_branch="feature/foo", base_branch="master")
            assert result == {
                "success": True,
                "diff": "diff --git a b",
                "truncated": False,
            }
            mock_get.assert_called_once()
            assert "/compare/master...feature/foo" in mock_get.call_args.args[1]

    def test_get_diff_pins_to_shas_when_given(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        mock_response = MagicMock(status_code=200, text="diff --git a b")
        with patch.object(github, "api_request", return_value=mock_response) as mock_get:
            result = github.get_diff(
                "PostHog/posthog",
                target_branch="feature/foo",
                base_branch="master",
                target_sha="abc123f",
                base_sha="def456a",
            )
            assert result["success"] is True
            assert "/compare/def456a...abc123f" in mock_get.call_args.args[1]

    def test_get_diff_maps_upstream_error(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        mock_response = MagicMock(status_code=404, text="Not Found")
        with patch.object(github, "api_request", return_value=mock_response):
            result = github.get_diff("PostHog/posthog", target_branch="feature/foo", base_branch="master")
        assert result == {"success": False, "error": "Not Found", "status_code": 404}

    def test_get_diff_handles_request_exception(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        with patch.object(github, "api_request", side_effect=GitHubIntegrationError("network error")):
            result = github.get_diff("PostHog/posthog", target_branch="feature/foo", base_branch="master")
        assert result["success"] is False
        assert result["status_code"] == 502

    def _github_for_org(self) -> GitHubIntegration:
        integration = self.create_integration(
            config={"account": {"name": "PostHog"}}, sensitive_config={"access_token": "ACCESS_TOKEN"}
        )
        return GitHubIntegration(integration)

    @staticmethod
    def _git_data_api_request(*, ref_status: int = 201):
        calls: list[tuple[str, str, Optional[dict]]] = []

        def _request(method, path, **kwargs):
            calls.append((method, path, kwargs.get("json_body")))
            if "/git/ref/heads/" in path and method == "GET":
                return MagicMock(status_code=200, **{"json.return_value": {"object": {"sha": "base-sha"}}})
            if "/git/commits/" in path:
                return MagicMock(status_code=200, **{"json.return_value": {"tree": {"sha": "base-tree"}}})
            if path.endswith("/git/trees"):
                return MagicMock(status_code=201, **{"json.return_value": {"sha": "new-tree"}})
            if path.endswith("/git/commits"):
                return MagicMock(status_code=201, **{"json.return_value": {"sha": "new-commit"}})
            if path.endswith("/git/refs"):
                return MagicMock(status_code=ref_status, text="Reference already exists")
            if "/git/refs/heads/" in path and method == "PATCH":
                return MagicMock(status_code=200)
            raise AssertionError(f"unexpected request {method} {path}")

        return _request, calls

    def test_commit_files_to_branch_writes_every_file_in_one_commit(self):
        github = self._github_for_org()
        request, calls = self._git_data_api_request()

        with patch.object(github, "api_request", side_effect=request):
            result = github.commit_files_to_branch(
                "community-skills", "community-skill/x", "main", {"a.md": "A", "b/c.md": "C"}, "msg"
            )

        assert result["success"] is True
        assert result["commit_sha"] == "new-commit"
        tree_body = next(body for _, path, body in calls if path.endswith("/git/trees"))
        assert {entry["path"] for entry in tree_body["tree"]} == {"a.md", "b/c.md"}
        assert tree_body["base_tree"] == "base-tree"
        # The branch reference is written last, so a failure earlier leaves no branch in the repo.
        assert calls[-1][1].endswith("/git/refs")

    def test_commit_files_to_branch_replaces_a_directory_rather_than_merging_into_it(self):
        github = self._github_for_org()
        request, calls = self._git_data_api_request()

        with patch.object(github, "api_request", side_effect=request):
            result = github.commit_files_to_branch(
                "community-skills",
                "community-skill/x",
                "main",
                {"skills/x/SKILL.md": "S", "skills/x/refs/g.md": "G", "README.md": "R"},
                "msg",
                replace_directory="skills/x",
            )

        assert result["success"] is True
        subtree_body, tree_body = (body for _, path, body in calls if path.endswith("/git/trees"))
        # No base_tree on the subtree, so it holds these files and nothing else. That is what makes a
        # path the caller dropped disappear instead of surviving from the base.
        assert "base_tree" not in subtree_body
        assert {entry["path"] for entry in subtree_body["tree"]} == {"SKILL.md", "refs/g.md"}
        assert tree_body["base_tree"] == "base-tree"
        assert {(entry["path"], entry["type"]) for entry in tree_body["tree"]} == {
            ("skills/x", "tree"),
            ("README.md", "blob"),
        }

    def test_commit_files_to_branch_force_updates_an_existing_branch(self):
        github = self._github_for_org()
        request, calls = self._git_data_api_request(ref_status=422)

        with patch.object(github, "api_request", side_effect=request):
            result = github.commit_files_to_branch(
                "community-skills", "community-skill/x", "main", {"a.md": "A"}, "msg"
            )

        assert result["success"] is True
        assert result["created_branch"] is False
        method, path, body = calls[-1]
        assert (method, path) == ("PATCH", "/repos/PostHog/community-skills/git/refs/heads/community-skill/x")
        assert body == {"sha": "new-commit", "force": True}

    @parameterized.expand([("deleted", 204), ("already gone", 404)])
    def test_delete_branch_treats_a_missing_branch_as_deleted(self, _name: str, status_code: int):
        github = self._github_for_org()
        with patch.object(github, "api_request", return_value=MagicMock(status_code=status_code)):
            assert github.delete_branch("community-skills", "community-skill/x")["success"] is True

    @parameterized.expand([("the ref is gone", 404, True), ("the ref is still there", 200, False)])
    def test_delete_branch_reads_the_ref_back_after_an_ambiguous_422(self, _name: str, recheck: int, deleted: bool):
        github = self._github_for_org()

        def _request(method, path, **kwargs):
            if method == "DELETE":
                return MagicMock(status_code=422, text="Validation failed")
            return MagicMock(status_code=recheck, **{"json.return_value": {"object": {"sha": "abc"}}})

        with patch.object(github, "api_request", side_effect=_request):
            result = github.delete_branch("community-skills", "community-skill/x")

        # A 422 the caller reads as success is a branch left on a public repo with nobody warned.
        assert result["success"] is deleted

    @parameterized.expand([("the expected commit", "mine", True), ("someone else's commit", "theirs", False)])
    def test_delete_branch_with_an_expected_sha_only_deletes_its_own_commit(
        self, _name: str, head_sha: str, deleted: bool
    ):
        github = self._github_for_org()
        methods: list[str] = []

        def _request(method, path, **kwargs):
            methods.append(method)
            if method == "GET":
                return MagicMock(status_code=200, **{"json.return_value": {"object": {"sha": head_sha}}})
            return MagicMock(status_code=204)

        with patch.object(github, "api_request", side_effect=_request):
            result = github.delete_branch("community-skills", "community-skill/x", expected_sha="mine")

        assert result["success"] is True
        assert ("DELETE" in methods) is deleted

    def test_get_open_pull_request_for_head_returns_number_and_url(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = [
            {
                "number": 7,
                "html_url": "https://github.com/PostHog/posthog/pull/7",
                "base": {"ref": "master"},
            }
        ]
        with patch.object(github, "_installation_authenticated_get", return_value=mock_response):
            assert github.get_open_pull_request_for_head("PostHog/posthog", "posthog-code/fix") == {
                "number": 7,
                "url": "https://github.com/PostHog/posthog/pull/7",
                "base": "master",
            }

    def test_get_open_pr_base_for_head_returns_base_ref_of_open_pr(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = [
            {
                "number": 7,
                "html_url": "https://github.com/PostHog/posthog/pull/7",
                "base": {"ref": "master"},
                "head": {"ref": "posthog-code/fix"},
            }
        ]
        with patch.object(github, "_installation_authenticated_get", return_value=mock_response) as mock_get:
            result = github.get_open_pr_base_for_head("PostHog/posthog", "posthog-code/fix")
        assert result == "master"
        # Query is scoped to open PRs whose head is the branch, in the repo owner's namespace.
        assert mock_get.call_args.kwargs["params"] == {
            "head": "PostHog:posthog-code/fix",
            "state": "open",
            "per_page": 1,
        }

    def test_get_open_pr_base_for_head_returns_none_when_no_open_pr(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = []
        with patch.object(github, "_installation_authenticated_get", return_value=mock_response):
            assert github.get_open_pr_base_for_head("PostHog/posthog", "master") is None

    def test_get_open_pr_base_for_head_returns_none_on_error(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        with patch.object(github, "_installation_authenticated_get", return_value=None):
            assert github.get_open_pr_base_for_head("PostHog/posthog", "posthog-code/fix") is None

    def test_get_pull_request_comments_merges_conversation_and_review_sorted(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)

        def fake_get(url, **kwargs):
            response = MagicMock(status_code=200)
            if "/issues/" in url:
                response.json.return_value = [
                    {
                        "id": 2,
                        "user": {"login": "bob", "avatar_url": "https://a/bob.png"},
                        "body": "second",
                        "created_at": "2026-07-06T10:00:00Z",
                        "html_url": "https://github.com/PostHog/posthog/pull/1#issuecomment-2",
                    }
                ]
            else:  # /pulls/{n}/comments — review comments
                response.json.return_value = [
                    {
                        "id": 1,
                        "user": {"login": "alice", "avatar_url": "https://a/alice.png"},
                        "body": "first",
                        "created_at": "2026-07-06T09:00:00Z",
                        "html_url": "https://github.com/PostHog/posthog/pull/1#discussion_r1",
                        "path": "posthog/models.py",
                    }
                ]
            return response

        with patch.object(github, "_installation_authenticated_get", side_effect=fake_get):
            result = github.get_pull_request_comments("PostHog/posthog", 1)

        assert result["success"] is True
        # Merged and sorted oldest-first across both sources; review comment carries its file path,
        # conversation comment does not.
        assert [(c["author"], c["comment_type"], c["path"]) for c in result["comments"]] == [
            ("alice", "review", "posthog/models.py"),
            ("bob", "conversation", None),
        ]

    def test_get_pull_request_comments_best_effort_when_one_source_fails(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)

        def fake_get(url, **kwargs):
            if "/issues/" in url:
                return None  # conversation fetch fails
            response = MagicMock(status_code=200)
            response.json.return_value = [
                {"id": 1, "user": {"login": "alice"}, "body": "x", "created_at": "2026-07-06T09:00:00Z"}
            ]
            return response

        with patch.object(github, "_installation_authenticated_get", side_effect=fake_get):
            result = github.get_pull_request_comments("PostHog/posthog", 1)

        assert result["success"] is True
        assert [c["author"] for c in result["comments"]] == ["alice"]

    @parameterized.expand(
        [
            ("success", "success", ("completed", "success")),
            ("failure", "failure", ("completed", "failure")),
            ("error", "error", ("completed", "failure")),
            ("pending", "pending", ("in_progress", None)),
            ("unknown", None, ("in_progress", None)),
        ]
    )
    def test_map_commit_status_state(self, _name, state, expected):
        assert GitHubIntegration._map_commit_status_state(state) == expected

    def test_get_pull_request_checks_merges_check_runs_and_statuses(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)

        def fake_get(url, **kwargs):
            response = MagicMock(status_code=200)
            if "/check-runs" in url:
                response.json.return_value = {
                    "check_runs": [
                        {
                            "name": "unit",
                            "status": "completed",
                            "conclusion": "failure",
                            "html_url": "https://github.com/checks/1",
                        }
                    ]
                }
            else:  # /status — legacy commit statuses
                response.json.return_value = {
                    "statuses": [{"context": "buildkite", "state": "success", "target_url": "https://bk/1"}]
                }
            return response

        with (
            patch.object(github, "get_pull_request", return_value={"success": True, "head_sha": "abc123f"}),
            patch.object(github, "_installation_authenticated_get", side_effect=fake_get),
        ):
            result = github.get_pull_request_checks("PostHog/posthog", 1)

        assert result["success"] is True
        assert result["checks"] == [
            {"name": "unit", "status": "completed", "conclusion": "failure", "url": "https://github.com/checks/1"},
            {"name": "buildkite", "status": "completed", "conclusion": "success", "url": "https://bk/1"},
        ]

    def test_get_pull_request_checks_follows_pagination(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)

        def fake_get(url, **kwargs):
            response = MagicMock(status_code=200)
            response.links = {}
            if "/check-runs" not in url:
                response.json.return_value = {"statuses": []}
            elif "page=2" in url:
                response.json.return_value = {
                    "check_runs": [
                        {
                            "name": "second page",
                            "status": "completed",
                            "conclusion": "success",
                        }
                    ]
                }
            else:
                response.json.return_value = {
                    "check_runs": [
                        {
                            "name": "first page",
                            "status": "completed",
                            "conclusion": "success",
                        }
                    ]
                }
                response.links = {
                    "next": {"url": "https://api.github.com/repos/PostHog/posthog/commits/abc123f/check-runs?page=2"}
                }
            return response

        with (
            patch.object(github, "get_pull_request", return_value={"success": True, "head_sha": "abc123f"}),
            patch.object(github, "_installation_authenticated_get", side_effect=fake_get),
        ):
            result = github.get_pull_request_checks("PostHog/posthog", 1)

        assert [check["name"] for check in result["checks"]] == ["first page", "second page"]

    @parameterized.expand([("check_runs",), ("statuses",)])
    def test_get_pull_request_checks_fails_when_later_page_is_unavailable(self, failing_source):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)

        def fake_get(url, **kwargs):
            source = "check_runs" if "/check-runs" in url else "statuses"
            if source == failing_source and "page=2" in url:
                return None

            response = MagicMock(status_code=200)
            response.links = {}
            response.json.return_value = {"check_runs": []} if source == "check_runs" else {"statuses": []}
            if source == failing_source:
                next_path = "check-runs" if source == "check_runs" else "status"
                response.links = {
                    "next": {"url": f"https://api.github.com/repos/PostHog/posthog/commits/abc123f/{next_path}?page=2"}
                }
            return response

        with (
            patch.object(github, "get_pull_request", return_value={"success": True, "head_sha": "abc123f"}),
            patch.object(github, "_installation_authenticated_get", side_effect=fake_get),
        ):
            result = github.get_pull_request_checks("PostHog/posthog", 1)

        expected_noun = "check run" if failing_source == "check_runs" else "commit status"
        assert result == {"success": False, "error": f"GitHub could not return every {expected_noun}"}

    def test_get_pull_request_checks_fails_when_pr_unavailable(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        with patch.object(github, "get_pull_request", return_value={"success": False, "error": "nope"}):
            result = github.get_pull_request_checks("PostHog/posthog", 1)
        assert result["success"] is False

    def test_get_diff_truncates_oversized_diff(self):
        from posthog.models.integration.github import _MAX_DIFF_CHARS

        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        oversized = "x" * (_MAX_DIFF_CHARS + 100)
        mock_response = MagicMock(status_code=200, text=oversized)
        with patch.object(github, "api_request", return_value=mock_response):
            result = github.get_diff("PostHog/posthog", target_branch="feature/foo", base_branch="master")
        assert result["success"] is True
        assert result["truncated"] is True
        assert len(result["diff"]) < len(oversized)
        assert result["diff"].startswith("x" * 100)
        assert "truncated" in result["diff"]

    @parameterized.expand(
        [
            ("repo_traversal", {"repository": "../../other/repo"}),
            ("repo_extra_path", {"repository": "owner/repo/contents/x"}),
            ("target_branch_traversal", {"target_branch": "../../../etc"}),
            ("target_branch_query", {"target_branch": "main?ref=x"}),
            ("base_branch_traversal", {"base_branch": "..%2f"}),
            ("target_sha_not_hex", {"target_sha": "main?ref=x"}),
            ("base_sha_not_hex", {"base_sha": "../../x"}),
        ]
    )
    def test_get_diff_rejects_unsafe_values(self, _name, overrides):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        kwargs: dict = {"repository": "PostHog/posthog", "target_branch": "feature/foo", "base_branch": "master"}
        kwargs.update(overrides)
        with patch.object(github, "api_request") as mock_get:
            result = github.get_diff(**kwargs)
        assert result["success"] is False
        assert result["status_code"] == 400
        mock_get.assert_not_called()

    def test_get_diff_allows_nested_branch_names(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        mock_response = MagicMock(status_code=200, text="diff --git a b")
        with patch.object(github, "api_request", return_value=mock_response) as mock_get:
            result = github.get_diff(
                "PostHog/posthog", target_branch="feature/nested/branch", base_branch="release/v1.2"
            )
        assert result["success"] is True
        mock_get.assert_called_once()

    @parameterized.expand(
        [
            ("traversal", "../../other/repo"),
            ("extra_path_segment", "owner/repo/contents/secret"),
            ("query_injection", "owner/repo?ref=x"),
            ("fragment", "owner/repo#"),
            ("bare_name", "repo"),
        ]
    )
    def test_first_for_team_repository_rejects_unsafe_path_without_probing(self, _name, repository):
        # The access check interpolates `repository` into an authenticated GET /repos/{repository};
        # an unsafe path must be rejected before any request fires, so it can't probe other endpoints.
        self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        with patch.object(GitHubIntegration, "installation_can_access_repository") as mock_access:
            result = GitHubIntegration.first_for_team_repository(self.team.id, repository)
        assert result is None
        mock_access.assert_not_called()

    def test_first_for_team_repository_allows_owner_repo(self):
        self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        with patch.object(GitHubIntegration, "installation_can_access_repository", return_value=True) as mock_access:
            result = GitHubIntegration.first_for_team_repository(self.team.id, "PostHog/posthog")
        assert result is not None
        mock_access.assert_called_once_with("PostHog/posthog")

    @parameterized.expand(
        [
            ("owner_repo", "PostHog/posthog", "https://api.github.com/repos/PostHog/posthog/pulls/123"),
            ("bare_repo", "posthog", "https://api.github.com/repos/PostHog/posthog/pulls/123"),
        ]
    )
    def test_close_pull_request_patches_state_closed(self, _name, repository, expected_url):
        # account.name lets a bare repo name resolve to {org}/{repo} via organization().
        integration = self.create_integration(
            config={"account": {"name": "PostHog"}}, sensitive_config={"access_token": "ACCESS_TOKEN"}
        )
        github = GitHubIntegration(integration)
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"number": 123, "state": "closed"}
        with patch.object(github, "_installation_authenticated_patch", return_value=mock_response) as mock_patch:
            result = github.close_pull_request(repository, 123)
        assert result == {"success": True, "number": 123, "state": "closed"}
        assert mock_patch.call_args.args[0] == expected_url
        assert mock_patch.call_args.kwargs["json_body"] == {"state": "closed"}

    def test_close_pull_request_maps_upstream_error(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        mock_response = MagicMock(status_code=404, text="Not Found")
        with patch.object(github, "_installation_authenticated_patch", return_value=mock_response):
            result = github.close_pull_request("PostHog/posthog", 123)
        assert result == {"success": False, "error": "Failed to close pull request: Not Found", "status_code": 404}

    def test_close_pull_request_from_url_parses_and_closes(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"number": 42, "state": "closed"}
        with patch.object(github, "_installation_authenticated_patch", return_value=mock_response) as mock_patch:
            result = github.close_pull_request_from_url("https://github.com/PostHog/posthog/pull/42")
        assert result["success"] is True
        assert mock_patch.call_args.args[0] == "https://api.github.com/repos/PostHog/posthog/pulls/42"

    def test_close_pull_request_from_url_rejects_non_pr_url(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        with patch.object(github, "_installation_authenticated_patch") as mock_patch:
            result = github.close_pull_request_from_url("https://github.com/PostHog/posthog/issues/42")
        assert result["success"] is False
        mock_patch.assert_not_called()

    def test_search_issues_drops_results_from_other_repositories(self):
        # Search-syntax operators in the query (e.g. "foo OR bar") can escape the repo:
        # qualifier, so results must be filtered by the repository they actually belong to.
        integration = self.create_integration(
            config={"account": {"name": "PostHog"}}, sensitive_config={"access_token": "ACCESS_TOKEN"}
        )
        github = GitHubIntegration(integration)
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {
            "items": [
                {
                    "number": 1,
                    "title": "In repo",
                    "html_url": "https://github.com/PostHog/posthog/issues/1",
                    "repository_url": "https://api.github.com/repos/PostHog/posthog",
                },
                {
                    "number": 2,
                    "title": "Other repo",
                    "html_url": "https://github.com/PostHog/other/issues/2",
                    "repository_url": "https://api.github.com/repos/PostHog/other",
                },
                {
                    "number": 3,
                    "title": "A pull request",
                    "html_url": "https://github.com/PostHog/posthog/pull/3",
                    "repository_url": "https://api.github.com/repos/PostHog/posthog",
                    "pull_request": {"url": "https://api.github.com/repos/PostHog/posthog/pulls/3"},
                },
            ]
        }
        with patch.object(github, "api_request", return_value=mock_response) as mock_request:
            results = github.search_issues("posthog", 'crash" repo:microsoft/vscode "')
        assert [result["id"] for result in results] == ["1"]
        assert results[0]["external_context"] == {"repository": "posthog", "number": 1}
        # The user's text is quoted so its qualifiers and operators match literally instead of
        # rewriting the query and filling the result page with foreign matches.
        sent_query = mock_request.call_args.kwargs["params"]["q"]
        assert sent_query == 'repo:PostHog/posthog "crash  repo:microsoft/vscode" in:title type:issue'

    def test_comment_on_pull_request_posts_to_issues_endpoint(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        mock_response = MagicMock(status_code=201)
        with patch.object(github, "_installation_authenticated_post", return_value=mock_response) as mock_post:
            result = github.comment_on_pull_request("PostHog/posthog", 123, "hello")
        assert result == {"success": True}
        # PR comments go through the issues endpoint, not /pulls.
        assert mock_post.call_args.args[0] == "https://api.github.com/repos/PostHog/posthog/issues/123/comments"
        assert mock_post.call_args.kwargs["json_body"] == {"body": "hello"}

    def test_comment_on_pull_request_from_url_parses_and_posts(self):
        integration = self.create_integration(sensitive_config={"access_token": "ACCESS_TOKEN"})
        github = GitHubIntegration(integration)
        mock_response = MagicMock(status_code=201)
        with patch.object(github, "_installation_authenticated_post", return_value=mock_response) as mock_post:
            result = github.comment_on_pull_request_from_url("https://github.com/PostHog/posthog/pull/42", "note")
        assert result["success"] is True
        assert mock_post.call_args.args[0] == "https://api.github.com/repos/PostHog/posthog/issues/42/comments"

    @parameterized.expand(
        [
            (
                "complete_headers",
                {
                    "X-RateLimit-Resource": "core",
                    "X-RateLimit-Remaining": "4998",
                    "X-RateLimit-Limit": "5000",
                    "X-RateLimit-Reset": "1704117600",
                },
                "core",
                4998,
                5000,
                1704117600,
            ),
            ("no_headers", {}, "unknown", None, None, None),
            (
                "no_resource_header",
                {
                    "X-RateLimit-Remaining": "4997",
                    "X-RateLimit-Limit": "5000",
                    "X-RateLimit-Reset": "1704117601",
                },
                "unknown",
                4997,
                5000,
                1704117601,
            ),
        ]
    )
    @patch("posthog.egress.transport.transport.requests.request")
    def test_github_api_request_metrics_include_integration_and_rate_limit_headers(
        self,
        _name: str,
        response_headers: dict[str, str],
        expected_resource: str,
        expected_remaining: int | None,
        expected_limit: int | None,
        expected_reset: int | None,
        mock_get,
    ):
        # Distinct installation id per case: the gauges are keyed by installation_id on a process-global
        # registry that isn't reset between methods, so a shared id would make the no_headers "== None"
        # assertion depend on parametrize ordering (another case sets the same (id, "unknown") series).
        integration = self.create_integration(
            {"installation_id": f"INSTALL-{_name}", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        response = MagicMock()
        response.status_code = 200
        response.headers = response_headers
        mock_get.return_value = response

        labels = {
            "installation_id": integration.integration_id,
            "method": "GET",
            "endpoint": "/repos/{owner}/{repo}",
            "status_code": "200",
            "source": "integration",
        }
        previous_count = REGISTRY.get_sample_value("github_integration_api_requests_total", labels) or 0

        with patch.object(GitHubIntegration, "access_token_expired", return_value=False):
            GitHubIntegration(integration).api_request(
                "GET",
                "/repos/PostHog/posthog",
                endpoint="/repos/{owner}/{repo}",
            )

        assert REGISTRY.get_sample_value("github_integration_api_requests_total", labels) == previous_count + 1
        assert (
            REGISTRY.get_sample_value(
                "github_integration_api_rate_limit_remaining",
                {"installation_id": integration.integration_id, "resource": expected_resource},
            )
            == expected_remaining
        )
        assert (
            REGISTRY.get_sample_value(
                "github_integration_api_rate_limit_limit",
                {"installation_id": integration.integration_id, "resource": expected_resource},
            )
            == expected_limit
        )
        assert (
            REGISTRY.get_sample_value(
                "github_integration_api_rate_limit_reset_timestamp_seconds",
                {"installation_id": integration.integration_id, "resource": expected_resource},
            )
            == expected_reset
        )

    @patch("posthog.egress.transport.transport.requests.request")
    def test_github_api_request_metrics_include_request_exceptions(self, mock_get):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        mock_get.side_effect = requests.RequestException("network failure")

        labels = {
            "installation_id": integration.integration_id,
            "method": "GET",
            "endpoint": "/repos/{owner}/{repo}",
            "status_code": "exception",
            "source": "integration",
        }
        previous_count = REGISTRY.get_sample_value("github_integration_api_requests_total", labels) or 0

        with (
            patch.object(GitHubIntegration, "access_token_expired", return_value=False),
            pytest.raises(GitHubIntegrationError),
        ):
            GitHubIntegration(integration).api_request(
                "GET",
                "/repos/PostHog/posthog",
                endpoint="/repos/{owner}/{repo}",
            )

        # GET retries the network error once; both attempts record an exception sample.
        assert REGISTRY.get_sample_value("github_integration_api_requests_total", labels) == previous_count + 2

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_github_integration_refresh_token(self, mock_client_request):
        mock_client_request.side_effect = self.mock_github_client_request(status_code=201)

        with freeze_time("2024-01-01T12:00:00Z"):
            integration = GitHubIntegration.integration_from_installation_id(
                "INSTALLATION_ID",
                self.team.id,
                self.user,
            )

            assert GitHubIntegration(integration).access_token_expired() is False

        with freeze_time("2024-01-01T14:00:00Z"):
            assert GitHubIntegration(integration).access_token_expired() is True

            GitHubIntegration(integration).refresh_access_token()
            assert GitHubIntegration(integration).access_token_expired() is False

        assert integration.config == {
            "installation_id": "INSTALLATION_ID",
            "account": {
                "name": "PostHog",
                "type": "Organization",
            },
            "repository_selection": "all",
            "refreshed_at": 1704117600,
            "expires_in": 3600,
        }

        assert integration.sensitive_config == {
            "access_token": "ACCESS_TOKEN",
        }

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_github_integration_persists_installation_permissions(self, mock_client_request):
        # The warehouse schema picker reads config["permissions"] to mark tables the installation
        # can't sync. Dropping this on connect or refresh silently returns the picker to offering
        # tables whose every sync 403s.
        mock_client_request.side_effect = self.mock_github_client_request(
            permissions={"contents": "read", "metadata": "read"}
        )
        integration = GitHubIntegration.integration_from_installation_id("INSTALLATION_ID", self.team.id, self.user)
        assert integration.config["permissions"] == {"contents": "read", "metadata": "read"}

        # A permission update to the App shows up on the next hourly token refresh, including for
        # integrations connected before this key was persisted at all.
        mock_client_request.side_effect = self.mock_github_client_request(
            permissions={"contents": "read", "metadata": "read", "deployments": "read"}
        )
        GitHubIntegration(integration).refresh_access_token()
        assert integration.config["permissions"] == {"contents": "read", "metadata": "read", "deployments": "read"}

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_github_integration_persists_repository_selection_on_refresh(self, mock_client_request):
        mock_client_request.side_effect = self.mock_github_client_request(repository_selection="all")
        integration = GitHubIntegration.integration_from_installation_id("INSTALLATION_ID", self.team.id, self.user)
        assert integration.config["repository_selection"] == "all"

        mock_client_request.side_effect = self.mock_github_client_request(repository_selection="selected")
        GitHubIntegration(integration).refresh_access_token()
        assert integration.config["repository_selection"] == "selected"

    @parameterized.expand(
        [
            ("installation_info_non_200", 503, 201, "installation_fetch_failed"),
            ("token_mint_non_201", 200, 400, "installation_token_failed"),
        ]
    )
    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_fetch_installation_access_fails_on_bad_status(
        self, _name, info_status, token_status, expected_code, mock_client_request
    ):
        def _client_request(endpoint, method="GET"):
            response = MagicMock()
            if method == "POST":
                response.status_code = token_status
                response.json.return_value = (
                    {"token": "TOKEN", "expires_at": "2099-01-01T00:00:00Z"} if token_status == 201 else {}
                )
            else:
                response.status_code = info_status
                response.json.return_value = (
                    {"account": {"login": "PostHog", "type": "Organization"}}
                    if info_status == 200
                    else {"message": "Service unavailable"}
                )
            return response

        mock_client_request.side_effect = _client_request

        with pytest.raises(GitHubInstallationAccessFetchError) as exc_info:
            GitHubIntegration.fetch_installation_access("INSTALLATION_ID")

        assert exc_info.value.code == expected_code

    @parameterized.expand(
        [
            ("numeric_placeholder", {"type": None, "name": "INSTALL"}, True, "PostHog"),
            ("missing_account", None, True, "PostHog"),
            ("already_resolved", {"type": "Organization", "name": "PostHog"}, False, "PostHog"),
        ]
    )
    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_ensure_account_name_only_fetches_for_placeholder_names(
        self, _name, account, expects_fetch, expected_name, mock_client_request
    ):
        mock_client_request.return_value = MagicMock(
            status_code=200, json=lambda: {"account": {"login": "PostHog", "type": "Organization"}}
        )
        config = {"installation_id": "INSTALL"}
        if account is not None:
            config["account"] = account
        integration = self.create_integration(config, {"access_token": "ACCESS_TOKEN"})

        healed = GitHubIntegration(integration).ensure_account_name()

        integration.refresh_from_db()
        assert healed is expects_fetch
        assert integration.config["account"]["name"] == expected_name
        assert mock_client_request.call_count == (1 if expects_fetch else 0)

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_ensure_account_name_backs_off_between_failed_attempts(self, mock_client_request):
        mock_client_request.return_value = MagicMock(status_code=503, json=lambda: {"message": "unavailable"})
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"type": None, "name": "INSTALL"}},
            {"access_token": "ACCESS_TOKEN"},
        )

        with freeze_time("2024-01-01T12:00:00Z"):
            assert GitHubIntegration(integration).ensure_account_name() is False
            assert GitHubIntegration(integration).ensure_account_name() is False
        assert mock_client_request.call_count == 1

        with freeze_time("2024-01-01T12:06:00Z"):
            GitHubIntegration(integration).ensure_account_name()
        assert mock_client_request.call_count == 2
        integration.refresh_from_db()
        assert integration.config["account"]["name"] == "INSTALL"

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_ensure_account_name_skips_unavailable_installation(self, mock_client_request):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "INSTALL"}, "installation_unavailable_since": 1},
            {"access_token": "ACCESS_TOKEN"},
        )

        assert GitHubIntegration(integration).ensure_account_name() is False
        mock_client_request.assert_not_called()

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_ensure_account_name_keeps_config_written_during_the_github_call(self, mock_client_request):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"type": None, "name": "INSTALL"}},
            {"access_token": "ACCESS_TOKEN"},
        )

        def _client_request(*_args, **_kwargs):
            # Stands in for a token refresh or installation webhook committing config mid-request.
            stored = Integration.objects.get(id=integration.id)
            Integration.objects.filter(id=integration.id).update(
                config={**stored.config, "repository_selection": "selected"}
            )
            return MagicMock(status_code=200, json=lambda: {"account": {"login": "PostHog", "type": "Organization"}})

        mock_client_request.side_effect = _client_request

        assert GitHubIntegration(integration).ensure_account_name() is True

        integration.refresh_from_db()
        assert integration.config["account"]["name"] == "PostHog"
        assert integration.config["repository_selection"] == "selected"

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_ensure_account_name_blocks_a_heal_that_lands_mid_call(self, mock_client_request):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"type": None, "name": "INSTALL"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        landed_mid_call = []

        def _client_request(*_args, **_kwargs):
            # Stands in for a second list request arriving before the first heal has recorded its attempt.
            reread = Integration.objects.get(id=integration.id)
            landed_mid_call.append(GitHubIntegration(reread).ensure_account_name())
            return MagicMock(status_code=200, json=lambda: {"account": {"login": "PostHog", "type": "Organization"}})

        mock_client_request.side_effect = _client_request

        assert GitHubIntegration(integration).ensure_account_name() is True

        assert landed_mid_call == [False]
        assert mock_client_request.call_count == 1

    @patch("posthog.models.integration.github.reload_integrations_on_workers")
    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_github_refresh_access_token_handles_errors(self, mock_client_request, mock_reload):
        """Test that errors field is set if refresh_access_token fails"""
        integration = self.create_integration({"expires_at": 3600}, {"token": "REFRESH"})
        mock_client_request.side_effect = self.mock_github_client_request(status_code=400, error_text="error")

        with freeze_time("2024-01-01T12:00:00Z"):
            integration.errors = ""
            integration.save()

            with pytest.raises(Exception):
                GitHubIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        assert integration.errors == "TOKEN_REFRESH_FAILED"
        assert integration.config["refresh_failure_count"] == 1

    @patch("posthog.models.integration.github.reload_integrations_on_workers")
    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_github_refresh_access_token_resets_errors(self, mock_client_request, mock_reload):
        """Test that errors field is reset to empty string after successful refresh_access_token"""
        mock_client_request.side_effect = self.mock_github_client_request(status_code=201)

        with freeze_time("2024-01-01T12:00:00Z"):
            integration = GitHubIntegration.integration_from_installation_id(
                "INSTALLATION_ID",
                self.team.id,
                self.user,
            )
            integration.errors = "TOKEN_REFRESH_FAILED"
            integration.save()

            GitHubIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        assert integration.errors == ""

    @parameterized.expand(
        [
            ("uninstalled_404", 404, "Not Found", {}, True),
            ("suspended_403", 403, "This installation has been suspended.", {}, True),
            ("rate_limited_403", 403, "You have exceeded a secondary rate limit", {"retry-after": "60"}, False),
            ("transient_500", 500, "Server Error", {}, False),
        ]
    )
    @patch("posthog.models.integration.github.reload_integrations_on_workers")
    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_github_refresh_disarms_proactive_refresh_only_for_dead_installation(
        self, _name, status_code, text, headers, expected_disarmed, mock_client_request, _mock_reload
    ):
        response = MagicMock(spec=requests.Response)
        response.status_code = status_code
        response.text = text
        response.headers = headers
        response.json.return_value = {}
        mock_client_request.return_value = response

        integration = self.create_integration(
            config={"installation_id": "INSTALL", "expires_in": 3600, "refreshed_at": int(time.time()) - 3600},
            sensitive_config={"access_token": "ACCESS_TOKEN"},
        )

        with pytest.raises(GitHubIntegrationError):
            GitHubIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        if expected_disarmed:
            assert "expires_in" not in integration.config
            assert "refreshed_at" not in integration.config
            assert GitHubIntegration(integration).access_token_expired() is False
            assert integration.config["installation_unavailable_since"]
            assert GitHubIntegration(integration).installation_unavailable() is True
        else:
            assert integration.config["expires_in"] == 3600
            assert "refreshed_at" in integration.config
            assert "installation_unavailable_since" not in integration.config
            assert GitHubIntegration(integration).installation_unavailable() is False

    @patch("posthog.models.integration.github.reload_integrations_on_workers")
    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_github_refresh_success_clears_installation_unavailable_marker(self, mock_client_request, _mock_reload):
        mock_client_request.side_effect = self.mock_github_client_request(status_code=201)
        integration = self.create_integration(
            config={"installation_id": "INSTALL", "installation_unavailable_since": 1700000000},
            sensitive_config={"access_token": "STALE_TOKEN"},
        )

        GitHubIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        assert "installation_unavailable_since" not in integration.config
        assert GitHubIntegration(integration).installation_unavailable() is False
        assert integration.sensitive_config["access_token"] == "ACCESS_TOKEN"
        assert "expires_in" in integration.config

    @patch("posthog.egress.transport.transport.requests.request")
    @patch("posthog.models.integration.github.GitHubIntegration.access_token_expired", return_value=False)
    def test_list_repositories_retries_transient_non_json_response(self, _mock_expired, mock_get):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )

        transient = MagicMock()
        transient.status_code = 502
        transient.json.side_effect = ValueError("not json")

        success = MagicMock()
        success.status_code = 200
        success.json.return_value = {
            "repositories": [
                {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
                {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
            ]
        }

        mock_get.side_effect = [transient, success]

        repos, has_more = GitHubIntegration(integration).list_repositories()

        assert repos == [
            {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
        ]
        assert has_more is False
        assert mock_get.call_count == 2

    @patch("posthog.egress.transport.transport.requests.request")
    @patch("posthog.models.integration.github.GitHubIntegration.access_token_expired", return_value=False)
    def test_list_repositories_raises_after_repeated_transient_non_json(self, _mock_expired, mock_get):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )

        transient_1 = MagicMock()
        transient_1.status_code = 502
        transient_1.json.side_effect = ValueError("not json")

        transient_2 = MagicMock()
        transient_2.status_code = 502
        transient_2.json.side_effect = ValueError("not json")

        mock_get.side_effect = [transient_1, transient_2]

        with pytest.raises(GitHubIntegrationError, match="list_repositories non-JSON response"):
            GitHubIntegration(integration).list_repositories()

        assert mock_get.call_count == 2

    @patch("posthog.egress.transport.transport.requests.request")
    @patch("posthog.models.integration.github.GitHubIntegration.access_token_expired", return_value=False)
    def test_list_all_repositories_raises_when_later_page_fails(self, _mock_expired, mock_get):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )

        first_page = MagicMock()
        first_page.status_code = 200
        first_page.json.return_value = {
            "repositories": [{"id": i, "name": f"repo-{i}", "full_name": f"PostHog/repo-{i}"} for i in range(100)]
        }

        second_page = MagicMock()
        second_page.status_code = 502
        second_page.json.return_value = {"message": "bad gateway"}

        # Page-1 succeeds. Page-2 fetch is retried once after transient 502.
        mock_get.side_effect = [first_page, second_page, second_page]

        with pytest.raises(GitHubIntegrationError, match="failed to list repositories"):
            GitHubIntegration(integration).list_all_repositories()

        assert mock_get.call_count == 3

    @patch("posthog.models.integration.github.GitHubIntegration.list_repositories")
    def test_list_all_repositories_fetches_all_pages(self, mock_list):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )

        first_page = [{"id": i, "name": f"repo-{i}", "full_name": f"PostHog/repo-{i}"} for i in range(100)]
        second_page = [{"id": i, "name": f"repo-{i}", "full_name": f"PostHog/repo-{i}"} for i in range(100, 130)]
        mock_list.side_effect = [
            (first_page, True),
            (second_page, False),
        ]

        repos = GitHubIntegration(integration).list_all_repositories()

        assert len(repos) == 130
        assert repos == first_page + second_page
        assert mock_list.call_args_list == [
            call(page=1, per_page=100),
            call(page=2, per_page=100),
        ]

    @patch("posthog.models.integration.github.GitHubIntegration.list_all_repositories")
    def test_list_cached_repositories_uses_cached_data_when_fresh(self, mock_list_all):
        cached_repositories = [
            {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
        ]
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        integration.repository_cache = cached_repositories
        integration.repository_cache_updated_at = timezone.now()
        integration.save(update_fields=["repository_cache", "repository_cache_updated_at"])

        labels = {
            "integration_id": str(integration.id),
            "cache": "repositories",
            "repository": "__all__",
            "result": "hit",
        }
        previous_count = REGISTRY.get_sample_value("github_integration_cache_accesses_total", labels) or 0

        repos, has_more = GitHubIntegration(integration).list_cached_repositories(limit=1, offset=1)

        assert repos == [{"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"}]
        assert has_more is False
        mock_list_all.assert_not_called()
        assert REGISTRY.get_sample_value("github_integration_cache_accesses_total", labels) == previous_count + 1

    @patch("posthog.models.integration.github.GitHubIntegration.list_all_repositories")
    def test_list_cached_repositories_surfaces_optional_fields_when_present(self, mock_list_all):
        cached_repositories = [
            {
                "id": 1,
                "name": "posthog",
                "full_name": "PostHog/posthog",
                "private": True,
                "default_branch": "master",
                "language": "Python",
                "pushed_at": "2026-06-01T00:00:00Z",
                "archived": False,
                "can_push": True,
            },
            {"id": 2, "name": "legacy", "full_name": "PostHog/legacy"},
        ]
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        integration.repository_cache = cached_repositories
        integration.repository_cache_updated_at = timezone.now()
        integration.save(update_fields=["repository_cache", "repository_cache_updated_at"])

        repos, _ = GitHubIntegration(integration).list_cached_repositories()

        assert repos[0] == {
            "id": 1,
            "name": "posthog",
            "full_name": "PostHog/posthog",
            "private": True,
            "default_branch": "master",
            "language": "Python",
            "pushed_at": "2026-06-01T00:00:00Z",
            "archived": False,
            "can_push": True,
        }
        # Repos cached before these fields existed keep their original shape — optional keys are omitted, not nulled.
        assert repos[1] == {"id": 2, "name": "legacy", "full_name": "PostHog/legacy"}
        mock_list_all.assert_not_called()

    @patch("posthog.models.integration.github.GitHubIntegration.list_all_repositories")
    def test_sync_repository_cache_respects_refresh_cooldown(self, mock_list_all):
        cached_repositories = [
            {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
        ]
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        integration.repository_cache = cached_repositories
        integration.repository_cache_updated_at = timezone.now()
        integration.save(update_fields=["repository_cache", "repository_cache_updated_at"])

        repos = GitHubIntegration(integration).sync_repository_cache(min_refresh_interval_seconds=60)

        assert repos == cached_repositories
        mock_list_all.assert_not_called()

    @patch("posthog.models.integration.github.GitHubIntegration.list_all_repositories")
    def test_sync_repository_cache_only_updates_timestamp_when_snapshot_unchanged(self, mock_list_all):
        cached_repositories = [
            {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
        ]
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        original_updated_at = timezone.now() - timedelta(minutes=5)
        integration.repository_cache = cached_repositories
        integration.repository_cache_updated_at = original_updated_at
        integration.save(update_fields=["repository_cache", "repository_cache_updated_at"])
        mock_list_all.return_value = cached_repositories

        with patch.object(integration, "save", wraps=integration.save) as mock_save:
            repos = GitHubIntegration(integration).sync_repository_cache()

        assert repos == cached_repositories
        mock_save.assert_called_once_with(update_fields=["repository_cache_updated_at"])
        integration.refresh_from_db()
        assert integration.repository_cache == cached_repositories
        assert integration.repository_cache_updated_at is not None
        assert integration.repository_cache_updated_at > original_updated_at

    @patch("posthog.models.integration.github.GitHubIntegration.list_all_repositories")
    def test_list_cached_repositories_populates_cache_on_miss(self, mock_list_all):
        fetched_repositories = [
            {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
        ]
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        mock_list_all.return_value = fetched_repositories

        labels = {
            "integration_id": str(integration.id),
            "cache": "repositories",
            "repository": "__all__",
            "result": "miss",
        }
        previous_count = REGISTRY.get_sample_value("github_integration_cache_accesses_total", labels) or 0

        repos, has_more = GitHubIntegration(integration).list_cached_repositories(limit=1, offset=0)

        integration.refresh_from_db()
        assert repos == [{"id": 1, "name": "posthog", "full_name": "PostHog/posthog"}]
        assert has_more is True
        assert integration.repository_cache == fetched_repositories
        assert integration.repository_cache_updated_at is not None
        mock_list_all.assert_called_once_with()
        assert REGISTRY.get_sample_value("github_integration_cache_accesses_total", labels) == previous_count + 1

    @patch("posthog.models.integration.github.GitHubIntegration.list_all_repositories")
    def test_list_cached_repositories_returns_stale_cache_on_refresh_error(self, mock_list_all):
        stale_repositories = [
            {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
        ]
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        integration.repository_cache = stale_repositories
        integration.repository_cache_updated_at = timezone.now() - timedelta(
            seconds=GITHUB_REPOSITORY_CACHE_TTL_SECONDS + 1
        )
        integration.save(update_fields=["repository_cache", "repository_cache_updated_at"])
        mock_list_all.side_effect = Exception("GitHub is slow")

        repos, has_more = GitHubIntegration(integration).list_cached_repositories(limit=10, offset=0)

        integration.refresh_from_db()
        assert repos == stale_repositories
        assert has_more is False
        assert integration.repository_cache == stale_repositories
        mock_list_all.assert_called_once_with()

    @patch("posthog.models.integration.github.GitHubIntegration.list_all_repositories")
    def test_list_cached_repositories_raises_on_refresh_error_without_cache(self, mock_list_all):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        mock_list_all.side_effect = Exception("GitHub is slow")

        with pytest.raises(Exception, match="GitHub is slow"):
            GitHubIntegration(integration).list_cached_repositories(limit=10, offset=0)

        integration.refresh_from_db()
        assert integration.repository_cache == []
        assert integration.repository_cache_updated_at is None
        mock_list_all.assert_called_once_with()

    def test_invalidate_github_repository_caches_for_installation_clears_team_and_personal_rows(self):
        from posthog.models.user_integration import UserIntegration

        team_integration = self.create_integration(
            {"installation_id": "12345", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        team_integration.integration_id = "12345"
        team_integration.repository_cache = [{"id": 1, "name": "a", "full_name": "org/a"}]
        team_integration.repository_cache_updated_at = timezone.now()
        team_integration.save(update_fields=["integration_id", "repository_cache", "repository_cache_updated_at"])

        user_integration = UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id="12345",
            config={"installation_id": "12345"},
            sensitive_config={"access_token": "ACCESS_TOKEN"},
            repository_cache=[{"id": 2, "name": "b", "full_name": "org/b"}],
            repository_cache_updated_at=timezone.now(),
        )

        invalidate_github_repository_caches_for_installation("12345")

        team_integration = Integration.objects.get(pk=team_integration.pk)
        user_integration = UserIntegration.objects.get(pk=user_integration.pk)
        assert team_integration.repository_cache_updated_at is None
        assert user_integration.repository_cache_updated_at is None
        assert team_integration.repository_cache == [{"id": 1, "name": "a", "full_name": "org/a"}]

    @patch("posthog.models.integration.github.GitHubIntegration.list_all_repositories")
    def test_list_cached_repositories_pages_with_full_cached_snapshot(self, mock_list_all):
        fetched_repositories = [{"id": i, "name": f"repo-{i}", "full_name": f"PostHog/repo-{i}"} for i in range(650)]
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        mock_list_all.return_value = fetched_repositories

        repos, has_more = GitHubIntegration(integration).list_cached_repositories(limit=25, offset=600)

        assert repos == fetched_repositories[600:625]
        assert has_more is True
        mock_list_all.assert_called_once_with()

    @parameterized.expand(
        [
            ("blank_search_returns_all", "   ", 10, 0, [1, 2, 3, 4], False),
            ("no_match_returns_empty", "missing", 10, 0, [], False),
            ("casefold_matches_owner_prefix", "POSTHOG", 10, 0, [1, 2, 3, 4], False),
            ("pagination_applies_after_filter", "posthog", 1, 1, [2], True),
        ]
    )
    @patch("posthog.models.integration.github.GitHubIntegration.list_all_repositories")
    def test_list_cached_repositories_filters_search_before_pagination(
        self,
        _name,
        search,
        limit,
        offset,
        expected_ids,
        expected_has_more,
        mock_list_all,
    ):
        fetched_repositories = [
            {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
            {"id": 3, "name": "code", "full_name": "PostHog/code"},
            {"id": 4, "name": "posthog-python", "full_name": "PostHog/posthog-python"},
        ]
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        mock_list_all.return_value = fetched_repositories

        repos, has_more = GitHubIntegration(integration).list_cached_repositories(
            search=search, limit=limit, offset=offset
        )

        assert [repo["id"] for repo in repos] == expected_ids
        assert has_more is expected_has_more
        mock_list_all.assert_called_once_with()

    @patch("posthog.models.integration.github.GitHubIntegration.list_all_repositories")
    def test_count_cached_repositories_counts_the_filtered_set_not_the_page(self, mock_list_all):
        mock_list_all.return_value = [
            {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
            {"id": 3, "name": "code", "full_name": "Acme/code"},
        ]
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        github = GitHubIntegration(integration)

        repos, has_more = github.list_cached_repositories(search="posthog", limit=1, offset=0)

        assert len(repos) == 1
        assert has_more is True
        assert github.count_cached_repositories(search="posthog") == 2
        assert github.count_cached_repositories() == 3
        mock_list_all.assert_called_once_with()

    @patch("posthog.models.integration.github.GitHubIntegration.list_branches")
    @patch("posthog.models.integration.github.GitHubIntegration.get_default_branch")
    def test_list_cached_branches_uses_cached_data_when_fresh(self, mock_default_branch, mock_list_branches):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        repo = "posthog/posthog"
        cache.set(
            GitHubIntegration(integration)._get_branch_cache_key(repo),
            {
                "branches": ["main", "develop", "feature/test"],
                "default_branch": "main",
                "updated_at": time.time(),
            },
        )

        labels = {
            "integration_id": str(integration.id),
            "cache": "branches",
            "repository": repo,
            "result": "hit",
        }
        previous_count = REGISTRY.get_sample_value("github_integration_cache_accesses_total", labels) or 0

        branches, default_branch, has_more = GitHubIntegration(integration).list_cached_branches(
            repo, limit=2, offset=1
        )

        assert branches == ["develop", "feature/test"]
        assert default_branch == "main"
        assert has_more is False
        mock_list_branches.assert_not_called()
        mock_default_branch.assert_not_called()
        assert REGISTRY.get_sample_value("github_integration_cache_accesses_total", labels) == previous_count + 1

    @patch("posthog.models.integration.github.GitHubIntegration.list_branches")
    @patch("posthog.models.integration.github.GitHubIntegration.get_default_branch")
    def test_list_cached_branches_filters_search_before_pagination(self, mock_default_branch, mock_list_branches):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        repo = "posthog/posthog"
        cache.set(
            GitHubIntegration(integration)._get_branch_cache_key(repo),
            {
                "branches": [
                    "main",
                    "feature/agent-cache",
                    "feature/agent-branch-search",
                    "fix/refresh-button",
                ],
                "default_branch": "main",
                "updated_at": time.time(),
            },
        )

        branches, default_branch, has_more = GitHubIntegration(integration).list_cached_branches(
            repo, search="feature/agent", limit=1, offset=1
        )

        assert branches == ["feature/agent-branch-search"]
        assert default_branch == "main"
        assert has_more is False
        mock_list_branches.assert_not_called()
        mock_default_branch.assert_not_called()

    @patch("posthog.models.integration.github.GitHubIntegration.list_branches")
    @patch("posthog.models.integration.github.GitHubIntegration.get_default_branch")
    def test_list_cached_branches_populates_cache_on_miss(self, mock_default_branch, mock_list_branches):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        repo = "posthog/posthog"
        mock_list_branches.return_value = (["develop", "feature/test"], False)
        mock_default_branch.return_value = "main"

        labels = {
            "integration_id": str(integration.id),
            "cache": "branches",
            "repository": repo,
            "result": "miss",
        }
        previous_count = REGISTRY.get_sample_value("github_integration_cache_accesses_total", labels) or 0

        branches, default_branch, has_more = GitHubIntegration(integration).list_cached_branches(
            repo, limit=2, offset=0
        )

        cached = cache.get(GitHubIntegration(integration)._get_branch_cache_key(repo))
        assert branches == ["develop", "feature/test"]
        assert default_branch == "main"
        assert has_more is False
        assert cached["branches"] == ["develop", "feature/test"]
        assert cached["default_branch"] == "main"
        mock_list_branches.assert_called_once_with(repo, limit=100, offset=0)
        mock_default_branch.assert_called_once_with(repo)
        assert REGISTRY.get_sample_value("github_integration_cache_accesses_total", labels) == previous_count + 1

    @patch("posthog.models.integration.github.GitHubIntegration.list_branches")
    @patch("posthog.models.integration.github.GitHubIntegration.get_default_branch")
    def test_list_cached_branches_returns_stale_cache_on_refresh_error(self, mock_default_branch, mock_list_branches):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        repo = "posthog/posthog"
        cache.set(
            GitHubIntegration(integration)._get_branch_cache_key(repo),
            {
                "branches": ["main", "develop"],
                "default_branch": "main",
                "updated_at": time.time() - (GITHUB_BRANCH_CACHE_TTL_SECONDS + 1),
            },
        )
        mock_list_branches.side_effect = Exception("GitHub is slow")

        branches, default_branch, has_more = GitHubIntegration(integration).list_cached_branches(
            repo, limit=10, offset=0
        )

        assert branches == ["main", "develop"]
        assert default_branch == "main"
        assert has_more is False
        mock_list_branches.assert_called_once_with(repo, limit=100, offset=0)
        mock_default_branch.assert_not_called()

    @patch("posthog.models.integration.github.GitHubIntegration.list_branches")
    @patch("posthog.models.integration.github.GitHubIntegration.get_default_branch")
    def test_list_cached_branches_keeps_cached_default_branch_on_refresh_failure(
        self, mock_default_branch, mock_list_branches
    ):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        repo = "posthog/posthog"
        cache.set(
            GitHubIntegration(integration)._get_branch_cache_key(repo),
            {
                "branches": ["main", "develop"],
                "default_branch": "main",
                "updated_at": time.time() - (GITHUB_BRANCH_CACHE_TTL_SECONDS + 1),
            },
        )
        mock_list_branches.return_value = (["main", "develop", "feature/test"], False)
        mock_default_branch.side_effect = Exception("GitHub is slow")

        branches, default_branch, has_more = GitHubIntegration(integration).list_cached_branches(
            repo, limit=10, offset=0
        )

        cached = cache.get(GitHubIntegration(integration)._get_branch_cache_key(repo))
        assert branches == ["main", "develop", "feature/test"]
        assert default_branch == "main"
        assert has_more is False
        assert cached["branches"] == ["main", "develop", "feature/test"]
        assert cached["default_branch"] == "main"
        mock_list_branches.assert_called_once_with(repo, limit=100, offset=0)
        mock_default_branch.assert_called_once_with(repo)

    @patch("posthog.models.integration.github.GitHubIntegration.list_branches")
    def test_list_cached_branches_raises_on_refresh_error_without_cache(self, mock_list_branches):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        repo = "posthog/posthog"
        mock_list_branches.side_effect = Exception("GitHub is slow")

        with pytest.raises(Exception, match="GitHub is slow"):
            GitHubIntegration(integration).list_cached_branches(repo, limit=10, offset=0)

        mock_list_branches.assert_called_once_with(repo, limit=100, offset=0)

    @patch("posthog.models.integration.github.GitHubIntegration.list_branches")
    def test_list_all_branches_fetches_all_pages(self, mock_list_branches):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        repo = "posthog/posthog"
        first_page = [f"branch-{i}" for i in range(100)]
        second_page = [f"branch-{i}" for i in range(100, 230)]
        mock_list_branches.side_effect = [
            (first_page, True),
            (second_page, False),
        ]

        branches = GitHubIntegration(integration).list_all_branches(repo)

        assert branches == first_page + second_page
        assert mock_list_branches.call_args_list == [
            call(repo, limit=100, offset=0),
            call(repo, limit=100, offset=100),
        ]

    @patch("posthog.models.integration.github.GitHubIntegration.list_branches")
    @patch("posthog.models.integration.github.GitHubIntegration.get_default_branch")
    def test_list_cached_branches_pages_with_full_cached_snapshot(self, mock_default_branch, mock_list_branches):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        repo = "posthog/posthog"
        first_page = [f"branch-{i}" for i in range(100)]
        second_page = [f"branch-{i}" for i in range(100, 200)]
        remaining_branches = [f"branch-{i}" for i in range(200, 1500)]
        mock_list_branches.side_effect = [
            (first_page, True),
            (second_page, True),
            (remaining_branches, False),
        ]
        mock_default_branch.return_value = "branch-1200"

        branches, default_branch, has_more = GitHubIntegration(integration).list_cached_branches(
            repo, limit=25, offset=1200
        )

        expected_branches = ["branch-1199"] + [f"branch-{i}" for i in range(1201, 1225)]
        assert branches == expected_branches
        assert default_branch == "branch-1200"
        assert has_more is True
        assert mock_list_branches.call_args_list == [
            call(repo, limit=100, offset=0),
            call(repo, limit=100, offset=100),
            call(repo, limit=100, offset=200),
        ]

    # --- raise_if_github_rate_limited ---

    @parameterized.expand(
        [
            ("429_no_body", 429, "", True),
            ("403_rate_limit_body", 403, "API rate limit exceeded for installation", True),
            ("403_other_body", 403, "Forbidden", False),
            ("200_ok", 200, "", False),
            ("404_not_found", 404, "", False),
        ]
    )
    def test_raise_if_github_rate_limited_detection(self, _name, status_code, body, should_raise):
        response = MagicMock()
        response.status_code = status_code
        response.text = body
        response.headers = {}

        if should_raise:
            with pytest.raises(GitHubRateLimitError):
                raise_if_github_rate_limited(response)
        else:
            raise_if_github_rate_limited(response)  # must not raise

    @freeze_time("2024-01-01 12:00:00")
    def test_raise_if_github_rate_limited_populates_fields(self):
        reset_timestamp = int(time.time()) + 60
        response = MagicMock()
        response.status_code = 429
        response.text = ""
        response.headers = {
            "x-ratelimit-reset": str(reset_timestamp),
            "retry-after": "30",
        }

        with pytest.raises(GitHubRateLimitError) as exc_info:
            raise_if_github_rate_limited(response)

        assert exc_info.value.reset_at == reset_timestamp
        assert exc_info.value.retry_after == 30

    @freeze_time("2024-01-01 12:00:00")
    def test_raise_if_github_rate_limited_derives_retry_after_from_reset_at(self):
        reset_timestamp = int(time.time()) + 45
        response = MagicMock()
        response.status_code = 429
        response.text = ""
        response.headers = {"x-ratelimit-reset": str(reset_timestamp)}

        with pytest.raises(GitHubRateLimitError) as exc_info:
            raise_if_github_rate_limited(response)

        assert exc_info.value.retry_after == 45

    # --- exception hierarchy ---

    def test_github_rate_limit_error_is_egress_error_not_fatal_integration_error(self):
        # Deliberately NOT a GitHubIntegrationError: a transient rate limit is retryable, not a fatal
        # integration failure, and it lives in the egress layer. Backoff filters key off these fields.
        err = GitHubRateLimitError("test", retry_after=45)
        assert not isinstance(err, GitHubIntegrationError)
        assert err.retry_after == 45

    # --- get_access_token ---

    def test_get_access_token_returns_token_when_not_expired(self):
        integration = self.create_integration(
            config={"expires_in": 3600, "refreshed_at": int(time.time())},
            sensitive_config={"access_token": "valid-token"},
        )
        github = GitHubIntegration(integration)
        assert github.get_access_token() == "valid-token"

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    @patch("posthog.models.integration.github.reload_integrations_on_workers")
    def test_get_access_token_refreshes_when_expired(self, mock_reload, mock_client_request):
        integration = self.create_integration(
            config={"expires_in": 3600, "refreshed_at": int(time.time()) - 7200},  # expired: refreshed 2h ago
            sensitive_config={"access_token": "old-token"},
        )
        mock_response = MagicMock()
        mock_response.status_code = 201
        dt = datetime.now(UTC) + timedelta(hours=1)
        mock_response.json.return_value = {
            "token": "new-token",
            "expires_at": dt.replace(tzinfo=None).isoformat(timespec="seconds") + "Z",
        }
        mock_client_request.return_value = mock_response

        github = GitHubIntegration(integration)
        token = github.get_access_token()

        assert token == "new-token"
        mock_client_request.assert_called_once()

    def test_get_access_token_raises_when_token_missing_after_refresh(self):
        integration = self.create_integration(
            config={"expires_in": 3600, "refreshed_at": int(time.time())},
            sensitive_config={},  # no access_token key
        )
        github = GitHubIntegration(integration)

        with pytest.raises(GitHubIntegrationError, match="Access token unavailable"):
            github.get_access_token()


def _create_github_integration(team) -> Integration:
    # integration_id mirrors production (set from config on install) — the egress gate and
    # tier store key on it; without it every call is identity-blind and skips both.
    return Integration.objects.create(
        team=team,
        kind="github",
        integration_id="INSTALL",
        config={"installation_id": "INSTALL", "account": {"name": "PostHog"}},
        sensitive_config={"access_token": "ACCESS_TOKEN"},
    )


class TestGitHubIntegrationGhApiGet(BaseTest):
    def _create_integration(self) -> Integration:
        return _create_github_integration(self.team)

    @patch("posthog.egress.transport.transport.requests.request")
    @patch("posthog.models.integration.github.GitHubIntegration.access_token_expired", return_value=False)
    def test_returns_parsed_json_body(self, _mock_expired, mock_get):
        ok = MagicMock()
        ok.status_code = 200
        ok.json.return_value = {"default_branch": "main"}
        mock_get.return_value = ok

        integration = self._create_integration()
        body = GitHubIntegration(integration)._gh_api_get("/repos/PostHog/posthog", endpoint="/repos/{owner}/{repo}")
        assert body == {"default_branch": "main"}

    @patch("posthog.egress.transport.transport.requests.request")
    @patch("posthog.egress.github.transport.consume_github_installation_sync", return_value=False)
    @patch("posthog.models.integration.github.GitHubIntegration.access_token_expired", return_value=False)
    def test_batch_instance_is_shed_when_budget_denied(self, _mock_expired, _mock_consume, mock_request):
        # Guards the lane plumbing: if the instance priority stops reaching the transport, BATCH
        # callers silently ride the never-shed CRITICAL lane again and denials stop deferring work.
        integration = self._create_integration()
        github = GitHubIntegration(integration, priority=Priority.BATCH)
        with pytest.raises(GitHubEgressBudgetExhausted):
            github.api_request("GET", "/repos/PostHog/posthog", endpoint="/repos/{owner}/{repo}")
        mock_request.assert_not_called()

    @patch("posthog.egress.transport.transport.requests.request")
    @patch("posthog.egress.github.transport.consume_github_installation_sync", return_value=False)
    @patch("posthog.models.integration.github.GitHubIntegration.access_token_expired", return_value=False)
    def test_critical_default_proceeds_when_budget_denied(self, _mock_expired, _mock_consume, mock_request):
        ok = MagicMock()
        ok.status_code = 200
        mock_request.return_value = ok

        integration = self._create_integration()
        response = GitHubIntegration(integration).api_request(
            "GET", "/repos/PostHog/posthog", endpoint="/repos/{owner}/{repo}"
        )
        assert response.status_code == 200
        mock_request.assert_called_once()

    @patch("posthog.egress.transport.transport.requests.request")
    @patch("posthog.models.integration.github.GitHubIntegration.access_token_expired", return_value=False)
    def test_retries_once_on_transient_5xx(self, _mock_expired, mock_get):
        transient = MagicMock()
        transient.status_code = 503
        transient.json.return_value = {}
        ok = MagicMock()
        ok.status_code = 200
        ok.json.return_value = {"ok": True}
        mock_get.side_effect = [transient, ok]

        integration = self._create_integration()
        body = GitHubIntegration(integration)._gh_api_get("/repos/PostHog/posthog", endpoint="/repos/{owner}/{repo}")
        assert body == {"ok": True}
        assert mock_get.call_count == 2

    @patch("posthog.egress.transport.transport.requests.request")
    @patch("posthog.models.integration.github.GitHubIntegration.access_token_expired", return_value=False)
    def test_raises_rate_limit_error_on_secondary_limit(self, _mock_expired, mock_get):
        resp = MagicMock()
        resp.status_code = 403
        resp.headers = {"retry-after": "5"}
        resp.json.return_value = {"message": "secondary rate limit"}
        mock_get.return_value = resp

        integration = self._create_integration()
        with pytest.raises(GitHubRateLimitError) as excinfo:
            GitHubIntegration(integration)._gh_api_get("/repos/PostHog/posthog", endpoint="/repos/{owner}/{repo}")
        assert excinfo.value.retry_after == 5

    @patch("posthog.egress.transport.transport.requests.request")
    @patch("posthog.models.integration.github.GitHubIntegration.access_token_expired", return_value=False)
    def test_detects_secondary_limit_from_body_when_headers_missing(self, _mock_expired, mock_get):
        resp = MagicMock()
        resp.status_code = 403
        resp.headers = {}
        resp.text = '{"message": "You have exceeded a secondary rate limit."}'
        resp.json.return_value = {"message": "You have exceeded a secondary rate limit."}
        mock_get.return_value = resp

        integration = self._create_integration()
        with pytest.raises(GitHubRateLimitError) as excinfo:
            GitHubIntegration(integration)._gh_api_get("/repos/PostHog/posthog", endpoint="/repos/{owner}/{repo}")
        assert excinfo.value.retry_after == 60

    @patch("posthog.egress.transport.transport.requests.request")
    @patch("posthog.models.integration.github.GitHubIntegration.refresh_access_token")
    @patch("posthog.models.integration.github.GitHubIntegration.access_token_expired", return_value=False)
    def test_refreshes_token_on_401(self, _mock_expired, mock_refresh, mock_get):
        unauth = MagicMock()
        unauth.status_code = 401
        unauth.json.return_value = {}
        ok = MagicMock()
        ok.status_code = 200
        ok.json.return_value = {"after_refresh": True}
        mock_get.side_effect = [unauth, ok]

        integration = self._create_integration()
        body = GitHubIntegration(integration)._gh_api_get("/repos/PostHog/posthog", endpoint="/repos/{owner}/{repo}")
        assert body == {"after_refresh": True}
        assert mock_refresh.called

    def test_rejects_path_without_leading_slash(self):
        integration = self._create_integration()
        with pytest.raises(ValueError, match="must start with"):
            GitHubIntegration(integration)._gh_api_get("repos/PostHog/posthog", endpoint="/repos/{owner}/{repo}")


class TestGitHubIntegrationGraphQL(BaseTest):
    def _create_integration(self) -> Integration:
        return _create_github_integration(self.team)

    @staticmethod
    def _graphql_response(body: dict) -> MagicMock:
        # GitHub returns transient GraphQL server errors as an HTTP 200 with an ``errors`` body,
        # so the retry decision hinges on the body, not the status code.
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = body
        return resp

    @patch("posthog.egress.transport.transport.requests.request")
    @patch("posthog.models.integration.github.GitHubIntegration.access_token_expired", return_value=False)
    def test_retries_transient_server_error_and_returns_data(self, _mock_expired, mock_request):
        # A 200-with-`errors` "Something went wrong" server error must be retried, not raised —
        # otherwise a transient GitHub blip permanently kills the in-flight follow-up run.
        transient = self._graphql_response(
            {"data": None, "errors": [{"message": "Something went wrong while executing your query. (abc123)"}]}
        )
        ok = self._graphql_response({"data": {"repository": {"name": "posthog"}}})
        mock_request.side_effect = [transient, ok]

        github = GitHubIntegration(self._create_integration())
        data = github._gh_graphql("query {}", {}, endpoint="/graphql:test")
        assert data == {"repository": {"name": "posthog"}}
        assert mock_request.call_count == 2

    @patch("posthog.egress.transport.transport.requests.request")
    @patch("posthog.models.integration.github.GitHubIntegration.access_token_expired", return_value=False)
    def test_gives_up_after_exhausting_transient_retries(self, _mock_expired, mock_request):
        # Guards against both a run-killing single attempt and an unbounded retry loop.
        transient = self._graphql_response(
            {"data": None, "errors": [{"type": "SERVICE_UNAVAILABLE", "message": "unavailable"}]}
        )
        mock_request.return_value = transient

        github = GitHubIntegration(self._create_integration())
        with pytest.raises(GitHubIntegrationError):
            github._gh_graphql("query {}", {}, endpoint="/graphql:test")
        assert mock_request.call_count == GitHubIntegration._GRAPHQL_TRANSIENT_ATTEMPTS

    @patch("posthog.egress.transport.transport.requests.request")
    @patch("posthog.models.integration.github.GitHubIntegration.access_token_expired", return_value=False)
    def test_does_not_retry_deterministic_error(self, _mock_expired, mock_request):
        # A deterministic error (bad query, missing field, permission) will never succeed on
        # retry, so it must raise on the first attempt rather than burn the retry budget.
        mock_request.return_value = self._graphql_response(
            {"data": None, "errors": [{"type": "FORBIDDEN", "message": "Resource not accessible by integration"}]}
        )

        github = GitHubIntegration(self._create_integration())
        with pytest.raises(GitHubIntegrationError):
            github._gh_graphql("query {}", {}, endpoint="/graphql:test")
        assert mock_request.call_count == 1

    @patch("posthog.egress.transport.transport.requests.request")
    @patch("posthog.models.integration.github.GitHubIntegration.access_token_expired", return_value=False)
    def test_returns_partial_data_with_field_errors(self, _mock_expired, mock_request):
        # When GitHub returns usable data alongside field-level errors, keep the data rather
        # than treating the response as a failure.
        mock_request.return_value = self._graphql_response(
            {"data": {"repository": {"name": "posthog"}}, "errors": [{"message": "field-level error"}]}
        )

        github = GitHubIntegration(self._create_integration())
        data = github._gh_graphql("query {}", {}, endpoint="/graphql:test")
        assert data == {"repository": {"name": "posthog"}}
        assert mock_request.call_count == 1


BABYSIT_PR_URL = "https://github.com/acme/widgets/pull/7"


def _babysit_thread(thread_id: str, *, is_resolved: bool = False, author: str = "reviewer", body: str = "fix this"):
    return {
        "id": thread_id,
        "isResolved": is_resolved,
        "path": "posthog/api.py",
        "comments": {
            "nodes": [
                {
                    "id": f"{thread_id}-C1",
                    "url": f"{BABYSIT_PR_URL}#discussion_{thread_id}",
                    "body": body,
                    "author": {"login": author},
                    "authorAssociation": "MEMBER",
                }
            ]
        },
    }


def _babysit_feedback(node_id: str, *, author: str = "reviewer", body: str = "please rename"):
    return {
        "id": node_id,
        "url": f"{BABYSIT_PR_URL}#issuecomment-{node_id}",
        "body": body,
        "author": {"login": author},
        "authorAssociation": "MEMBER",
    }


class TestGitHubIntegrationPullRequestBabysitSnapshot(BaseTest):
    def _github(self) -> GitHubIntegration:
        return GitHubIntegration(_create_github_integration(self.team))

    @staticmethod
    def _payload(**overrides) -> dict:
        pull_request: dict = {
            "url": BABYSIT_PR_URL,
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "headRefOid": "head1",
            "author": {"login": "posthog-bot"},
            "reviewThreads": {"nodes": []},
            "comments": {"nodes": []},
            "reviews": {"nodes": []},
            "commits": {"nodes": [{"commit": {"statusCheckRollup": None}}]},
        }
        pull_request.update(overrides)
        return {"repository": {"pullRequest": pull_request}}

    _FAILING_CONTEXT = {
        "__typename": "CheckRun",
        "name": "backend",
        "conclusion": "FAILURE",
        "detailsUrl": "https://ci.example.com/1",
        "checkSuite": None,
    }

    def test_resolved_threads_and_self_or_empty_feedback_are_dropped(self):
        payload = self._payload(
            reviewThreads={"nodes": [_babysit_thread("T1", is_resolved=True), _babysit_thread("T2")]},
            comments={
                "nodes": [
                    _babysit_feedback("M1", author="posthog-bot"),
                    _babysit_feedback("M2", body="   "),
                    _babysit_feedback("M3"),
                ]
            },
            reviews={"nodes": [_babysit_feedback("R1", author="posthog-bot"), _babysit_feedback("R2")]},
        )

        with patch.object(GitHubIntegration, "_gh_graphql", return_value=payload):
            result = self._github().get_pull_request_babysit_snapshot(BABYSIT_PR_URL)

        assert [thread["id"] for thread in result["unresolved_threads"]] == ["T2"]
        assert [comment["id"] for comment in result["comments"]] == ["M3", "R2"]

    @parameterized.expand(
        [
            ("MERGED", False, "merged"),
            ("CLOSED", False, "closed"),
            ("OPEN", True, "draft"),
            ("OPEN", False, "open"),
        ]
    )
    def test_pr_state_mapping(self, gql_state, is_draft, expected):
        payload = self._payload(state=gql_state, isDraft=is_draft)

        with patch.object(GitHubIntegration, "_gh_graphql", return_value=payload):
            result = self._github().get_pull_request_babysit_snapshot(BABYSIT_PR_URL)

        assert result["state"] == expected

    @parameterized.expand(
        [
            ("CONFLICTING", True),
            ("MERGEABLE", False),
            ("UNKNOWN", False),
        ]
    )
    def test_only_a_conflicting_merge_state_flags_a_conflict(self, gql_mergeable, expected):
        payload = self._payload(mergeable=gql_mergeable)

        with patch.object(GitHubIntegration, "_gh_graphql", return_value=payload):
            result = self._github().get_pull_request_babysit_snapshot(BABYSIT_PR_URL)

        assert result["has_conflict"] is expected

    def test_extracts_only_failing_checks_with_workflow_scoped_keys(self):
        rollup = {
            "contexts": {
                "nodes": [
                    {
                        "__typename": "CheckRun",
                        "name": "backend",
                        "conclusion": "FAILURE",
                        "detailsUrl": "https://ci.example.com/1",
                        "checkSuite": {"workflowRun": {"workflow": {"name": "CI"}}},
                    },
                    {"__typename": "CheckRun", "name": "frontend", "conclusion": "SUCCESS", "checkSuite": None},
                    {"__typename": "CheckRun", "name": "flaky", "conclusion": "TIMED_OUT", "checkSuite": None},
                    {
                        "__typename": "StatusContext",
                        "context": "vercel",
                        "state": "ERROR",
                        "targetUrl": "https://vercel.example.com/1",
                    },
                    {"__typename": "StatusContext", "context": "netlify", "state": "SUCCESS"},
                ]
            },
        }
        payload = self._payload(commits={"nodes": [{"commit": {"statusCheckRollup": rollup}}]})

        with patch.object(GitHubIntegration, "_gh_graphql", return_value=payload):
            result = self._github().get_pull_request_babysit_snapshot(BABYSIT_PR_URL)

        assert [check["key"] for check in result["failing_checks"]] == ["CI/backend", "flaky", "vercel"]
        assert result["failing_checks"][0]["details_url"] == "https://ci.example.com/1"

    @parameterized.expand(
        [
            ("FAILURE", [], [("ci-rollup-failing", f"{BABYSIT_PR_URL}/checks")]),
            ("ERROR", [], [("ci-rollup-failing", f"{BABYSIT_PR_URL}/checks")]),
            ("FAILURE", [_FAILING_CONTEXT], [("backend", "https://ci.example.com/1")]),
            ("SUCCESS", [], []),
            ("PENDING", [], []),
        ]
    )
    def test_rollup_state_backstops_checks_missing_from_the_context_page(self, rollup_state, context_nodes, expected):
        rollup = {"state": rollup_state, "contexts": {"nodes": context_nodes}}
        payload = self._payload(commits={"nodes": [{"commit": {"statusCheckRollup": rollup}}]})

        with patch.object(GitHubIntegration, "_gh_graphql", return_value=payload):
            result = self._github().get_pull_request_babysit_snapshot(BABYSIT_PR_URL)

        assert [(check["key"], check["details_url"]) for check in result["failing_checks"]] == expected

    def test_invalid_pull_request_url_is_reported_as_failure_without_calling_github(self):
        with patch.object(GitHubIntegration, "_gh_graphql") as mock_graphql:
            result = self._github().get_pull_request_babysit_snapshot("https://example.com/not/a/pull-request")

        assert result["success"] is False
        mock_graphql.assert_not_called()

    def test_missing_pull_request_is_reported_as_failure(self):
        with patch.object(GitHubIntegration, "_gh_graphql", return_value={"repository": {"pullRequest": None}}):
            result = self._github().get_pull_request_babysit_snapshot(BABYSIT_PR_URL)

        assert result["success"] is False
