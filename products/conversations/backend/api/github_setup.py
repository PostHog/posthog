"""GitHub Issues channel setup endpoints for Conversations."""

import re
from typing import Any, cast

import structlog
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.user import User

from products.conversations.backend.permissions import IsConversationsAdmin
from products.conversations.backend.tasks import create_github_issue

logger = structlog.get_logger(__name__)


class GithubStatusView(APIView):
    permission_classes = [IsAuthenticated, IsConversationsAdmin]

    def get(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        team = user.current_team
        settings_dict = team.conversations_settings or {}

        integration_id = settings_dict.get("github_integration_id")
        integration_info = None
        if integration_id:
            integration = Integration.objects.filter(id=integration_id, team=team, kind="github").first()
            if integration:
                account = integration.config.get("account", {})
                integration_info = {
                    "id": integration.id,
                    "name": account.get("name", ""),
                }

        return Response(
            {
                "connected": settings_dict.get("github_enabled", False),
                "integration": integration_info,
                "repos": settings_dict.get("github_repos", []),
            }
        )


class GithubConnectView(APIView):
    permission_classes = [IsAuthenticated, IsConversationsAdmin]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        team = user.current_team
        integration_id = request.data.get("integration_id")
        if not integration_id:
            return Response({"error": "integration_id is required"}, status=400)

        try:
            integration = Integration.objects.get(id=integration_id, team=team, kind="github")
        except Integration.DoesNotExist:
            return Response({"error": "GitHub integration not found"}, status=404)

        settings_dict = team.conversations_settings or {}
        settings_dict["github_enabled"] = True
        settings_dict["github_integration_id"] = integration.id
        if "github_repos" not in settings_dict:
            settings_dict["github_repos"] = []
        team.conversations_settings = settings_dict
        team.save(update_fields=["conversations_settings"])

        return Response({"ok": True})


class GithubDisconnectView(APIView):
    permission_classes = [IsAuthenticated, IsConversationsAdmin]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        team = user.current_team
        settings_dict = team.conversations_settings or {}
        settings_dict["github_enabled"] = False
        settings_dict.pop("github_integration_id", None)
        settings_dict.pop("github_repos", None)
        team.conversations_settings = settings_dict
        team.save(update_fields=["conversations_settings"])

        return Response({"ok": True})


class GithubReposView(APIView):
    permission_classes = [IsAuthenticated, IsConversationsAdmin]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        team = user.current_team
        settings_dict = team.conversations_settings or {}
        integration_id = settings_dict.get("github_integration_id")
        if not integration_id:
            return Response({"error": "GitHub not connected"}, status=400)

        try:
            integration = Integration.objects.get(id=integration_id, team=team, kind="github")
        except Integration.DoesNotExist:
            return Response({"error": "GitHub integration not found"}, status=404)

        github = GitHubIntegration(integration)
        repos, _has_more = github.list_cached_repositories(limit=200)

        return Response(
            {
                "repos": [
                    {"full_name": r.get("full_name", ""), "name": r.get("name", "")}
                    for r in repos
                    if r.get("full_name")
                ]
            }
        )


class GithubSelectReposView(APIView):
    permission_classes = [IsAuthenticated, IsConversationsAdmin]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        team = user.current_team
        repos = request.data.get("repos", [])
        if not isinstance(repos, list):
            return Response({"error": "repos must be a list"}, status=400)
        if len(repos) > 100:
            return Response({"error": "Too many repositories (max 100)"}, status=400)

        settings_dict = team.conversations_settings or {}
        integration_id = settings_dict.get("github_integration_id")
        if not integration_id:
            return Response({"error": "GitHub not connected"}, status=400)

        # Validate repos match GitHub owner/repo format (alphanumeric, hyphens, dots, underscores)
        repo_pattern = re.compile(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$")
        validated: list[str] = []
        for repo in repos:
            if isinstance(repo, str) and len(repo) <= 256 and repo_pattern.match(repo):
                validated.append(repo)

        settings_dict["github_repos"] = validated
        team.conversations_settings = settings_dict
        team.save(update_fields=["conversations_settings"])

        return Response({"ok": True, "repos": validated})


class GithubCreateIssueView(APIView):
    permission_classes = [IsAuthenticated, IsConversationsAdmin]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        team = user.current_team
        settings_dict = team.conversations_settings or {}
        if not settings_dict.get("github_enabled"):
            return Response({"error": "GitHub channel not enabled"}, status=400)

        integration_id = settings_dict.get("github_integration_id")
        if not integration_id:
            return Response({"error": "GitHub not connected"}, status=400)

        repo = request.data.get("repo", "")
        title = request.data.get("title", "")[:256] if isinstance(request.data.get("title"), str) else ""
        body = request.data.get("body", "")[:65_536] if isinstance(request.data.get("body"), str) else ""
        labels = request.data.get("labels")

        if not repo or not title:
            return Response({"error": "repo and title are required"}, status=400)

        if labels is not None:
            if not isinstance(labels, list) or len(labels) > 20 or not all(isinstance(label, str) for label in labels):
                return Response({"error": "labels must be a list of up to 20 strings"}, status=400)

        repo_pattern = re.compile(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$")
        if not repo_pattern.match(repo):
            return Response({"error": "Invalid repository format"}, status=400)

        allowed_repos: list[str] = settings_dict.get("github_repos", [])
        if repo not in allowed_repos:
            return Response({"error": "Repository not in monitored list"}, status=400)

        cast(Any, create_github_issue).delay(
            team_id=team.id,
            integration_id=integration_id,
            repo=repo,
            title=title,
            body=body,
            labels=labels,
        )

        return Response({"ok": True})
