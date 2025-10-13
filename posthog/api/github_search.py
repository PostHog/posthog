from django.conf import settings

import structlog
from rest_framework import serializers, viewsets
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.integration import GitHubIntegration, Integration

logger = structlog.get_logger(__name__)


class GitHubSearchSerializer(serializers.Serializer):
    owner = serializers.CharField(required=True)
    repository = serializers.CharField(required=True)
    query = serializers.CharField(required=True)


class GitHubSearchViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    def create(self, request):
        serializer = GitHubSearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        owner = serializer.validated_data["owner"]
        repository = serializer.validated_data["repository"]
        query = serializer.validated_data["query"]

        result = None

        if settings.GITHUB_TOKEN:
            result = GitHubIntegration.search_code_with_token(
                query=query,
                token=settings.GITHUB_TOKEN,
                repository=repository,
                owner=owner,
            )

            if result.get("success") and result.get("total_count", 0) > 0:
                items = result.get("items", [])
                if items:
                    return Response(
                        {
                            "found": True,
                            "url": items[0].get("html_url"),
                            "path": items[0].get("path"),
                            "repository": items[0].get("repository", {}).get("full_name"),
                        }
                    )

        integration = Integration.objects.filter(team_id=self.team.id, kind="github").first()
        if integration:
            github = GitHubIntegration(integration)
            result = github.search_code(query=query, repository=repository, owner=owner)

            if result.get("success") and result.get("total_count", 0) > 0:
                items = result.get("items", [])
                if items:
                    return Response(
                        {
                            "found": True,
                            "url": items[0].get("html_url"),
                            "path": items[0].get("path"),
                            "repository": items[0].get("repository", {}).get("full_name"),
                        }
                    )

        if result and not result.get("success"):
            logger.warning(
                "github_search_failed",
                error=result.get("error"),
                team_id=self.team.id,
                owner=owner,
                repository=repository,
            )

        return Response(
            {
                "found": False,
                "error": result.get("error") if result else "No results found",
            }
        )
