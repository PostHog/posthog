import urllib.parse

from django.conf import settings

import requests
import structlog
from rest_framework import viewsets
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.integration import GitHubIntegration, Integration

logger = structlog.get_logger(__name__)


def get_github_file_url_by_code_sample(code_sample: str, token: str, owner: str, repository: str) -> str | None:
    """Search GitHub code using the Code Search API. Returns URL to first match or None."""
    search_query = f"{code_sample} repo:{owner}/{repository}"
    encoded_query = urllib.parse.quote(search_query)
    url = f"https://api.github.com/search/code?q={encoded_query}"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.text-match+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            items = data.get("items", [])
            if items:
                return items[0].get("html_url")
            return None
        else:
            logger.warning("github_code_search_failed", status_code=response.status_code)
            return None
    except requests.exceptions.RequestException as e:
        logger.exception("github_code_search_request_failed", error=str(e))
        return None


class GitHubSearchViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    @action(methods=["GET"], detail=False, url_path="search")
    def search(self, request, **kwargs):
        owner = request.GET.get("owner")
        repository = request.GET.get("repository")
        code_sample = request.GET.get("code_sample")

        if not owner or not repository or not code_sample:
            return Response({"found": False, "error": "owner, repository, and code_sample are required"})

        url = None

        # Try with posthogs token first (public repos)
        if settings.GITHUB_TOKEN:
            url = get_github_file_url_by_code_sample(
                code_sample=code_sample, token=settings.GITHUB_TOKEN, owner=owner, repository=repository
            )
            if url:
                return Response({"found": True, "url": url})

        # Try with assigned github integration (private repos)
        integration = Integration.objects.filter(team_id=self.team.id, kind="github").first()

        if integration:
            github = GitHubIntegration(integration)

            if github.access_token_expired():
                github.refresh_access_token()

            token = github.integration.sensitive_config.get("access_token")
            if token:
                url = get_github_file_url_by_code_sample(
                    code_sample=code_sample, token=token, owner=owner, repository=repository
                )
                if url:
                    return Response({"found": True, "url": url})

        return Response({"found": False})
