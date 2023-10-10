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
        q = request.GET.get("q", "").strip()

        vector = SearchVector("name", "description")
        query = SearchQuery(q)
        q1 = Dashboard.objects.annotate(
            rank=SearchRank(vector, query), type=models.Value("dashboard", output_field=models.CharField())
        ).filter(rank__gt=0.0)
        q2 = FeatureFlag.objects.annotate(
            rank=SearchRank(SearchVector("name"), query),
            type=models.Value("feature_flag", output_field=models.CharField()),
        ).filter(rank__gt=0.0)
        q3 = q1 = Experiment.objects.annotate(
            rank=SearchRank(vector, query), type=models.Value("experiment", output_field=models.CharField())
        ).filter(rank__gt=0.0)

        q = q1.union(q2, q3).order_by("-rank")
        # having rank > 0
        d = q.values("type", "pk", "rank", "name")

        counts = {"dashboard": q1.count(), "feature_flag": q2.count(), "experiment": q3.count()}

        return Response({"results": d, "counts": counts})
