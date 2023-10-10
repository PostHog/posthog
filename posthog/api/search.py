from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import Value, CharField
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
        if len(q) == 0:
            return Response(
                {
                    "results": [],
                    "counts": {"dashboard": None, "feature_flag": None, "experiment": None},
                }
            )

        vector = SearchVector("name", "description")
        query = SearchQuery(":* & ".join(q.split()).strip() + ":*", search_type="raw")
        q1 = Dashboard.objects.annotate(
            rank=SearchRank(vector, query, cover_density=True, normalization=Value(1)),
            type=Value("dashboard", output_field=CharField()),
        ).filter(rank__gt=0.0, team=self.team)
        q2 = FeatureFlag.objects.annotate(
            rank=SearchRank(SearchVector("name"), query, cover_density=True, normalization=Value(1)),
            type=Value("feature_flag", output_field=CharField()),
        ).filter(rank__gt=0.0, team=self.team)
        q3 = q1 = Experiment.objects.annotate(
            rank=SearchRank(vector, query, cover_density=True, normalization=Value(1)),
            type=Value("experiment", output_field=CharField()),
        ).filter(rank__gt=0.0, team=self.team)

        q = q1.union(q2, q3).order_by("-rank")
        # having rank > 0
        d = q.values("type", "pk", "rank", "name")

        counts = {"dashboard": q1.count(), "feature_flag": q2.count(), "experiment": q3.count()}

        return Response({"results": d, "counts": counts, "sql": str(q.query)})
