from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db import models
from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.models import Dashboard, FeatureFlag, Experiment


class SearchViewSet(StructuredViewSetMixin, viewsets.ViewSet):
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    def list(self, request: Request, **kw) -> HttpResponse:
        vector = SearchVector("name", "description")
        query = SearchQuery("metric")
        q1 = Dashboard.objects.annotate(
            rank=SearchRank(vector, query), type=models.Value("dashboard", output_field=models.CharField())
        ).order_by("-rank")
        q2 = FeatureFlag.objects.annotate(
            rank=SearchRank(SearchVector("name"), query),
            type=models.Value("feature_flag", output_field=models.CharField()),
        ).order_by("-rank")
        q3 = q1 = Experiment.objects.annotate(
            rank=SearchRank(vector, query), type=models.Value("dashboard", output_field=models.CharField())
        ).order_by("-rank")

        q = q1.union(q2, q3)
        # having rank > 0

        return Response({"ranked": q.values("type", "pk", "rank")})
