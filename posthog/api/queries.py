from rest_framework import response, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from posthog.api.insight import InsightViewSet
from posthog.api.routing import StructuredViewSetMixin
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


class QueryViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    @action(url_path="q", methods=["GET"], detail=False)
    def query(self, request, *args, **kwargs) -> response.Response:
        query_type = request.query_params.get("type")
        if query_type == "legacy_trends":
            insight_trend_view = InsightViewSet.as_view({"get": "trend"})
            view_response = insight_trend_view(request._request, *args, **kwargs)
            return response.Response(view_response.data, status=view_response.status_code)
        else:
            raise ValidationError(detail=f"{query_type} is not a valid query type")
