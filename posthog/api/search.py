import re
from typing import Any
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import Model, Value, CharField, F, QuerySet
from django.db.models.functions import Cast
from django.http import HttpResponse
from rest_framework import viewsets, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.models import Action, Cohort, Insight, Dashboard, FeatureFlag, Experiment, Team

LIMIT = 25

ENTITIES = [Action, Cohort, Insight, Dashboard, FeatureFlag, Experiment]


def class_to_type(klass: type[Model]):
    """Converts the class name to snake case."""
    return re.sub("(?!^)([A-Z]+)", r"_\1", klass.__name__).lower()


entity_map = {class_to_type(entity): {"klass": entity} for entity in ENTITIES}


class QuerySerializer(serializers.Serializer):
    q = serializers.CharField(required=False, default="")
    entities = serializers.MultipleChoiceField(required=False, choices=[class_to_type(entity) for entity in ENTITIES])

    def validate_q(self, value: str | None):
        return process_query(value)


class SearchViewSet(StructuredViewSetMixin, viewsets.ViewSet):
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    def list(self, request: Request, **kw) -> HttpResponse:
        query_serializer = QuerySerializer(data=self.request.query_params)
        query_serializer.is_valid(raise_exception=True)
        params = query_serializer.validated_data

        counts = {}
        entities = params["entities"] if len(params["entities"]) > 0 else set(entity_map.keys())
        query = params["q"]

        # empty queryset to union things onto it
        qs = Dashboard.objects.annotate(type=Value("empty", output_field=CharField())).filter(team=self.team).none()

        for klass in [entity_map[entity]["klass"] for entity in entities]:
            klass_qs, entity_name = class_queryset(klass, team=self.team, query=query)
            qs = qs.union(klass_qs)
            counts[entity_name] = klass_qs.count()

        if query:
            qs = qs.order_by("-rank")

        return Response({"results": qs[:LIMIT], "counts": counts})


UNSAFE_CHARACTERS = r"[\'&|!<>():]"
"""Characters unsafe in a `tsquery`."""


def process_query(query: str):
    """
    Converts a query string into a to_tsquery compatible string, where
    the last word is a prefix match. This allows searching as you type.
    """
    query = re.sub(UNSAFE_CHARACTERS, " ", query).strip()
    query = re.sub(r"\s+", " & ", query)  # combine words with &
    if len(query) == 0:
        return None
    query += ":*"  # prefix match last word
    return query


def class_queryset(klass: type[Model], team: Team, query: str | None):
    """Builds a queryset for the class."""
    type = class_to_type(klass)
    values = ["type", "result_id", "name"]

    qs: QuerySet[Any] = klass.objects.filter(team=team)
    qs = qs.annotate(type=Value(type, output_field=CharField()))

    if type == "insight":
        qs = qs.annotate(result_id=F("short_id"))
    else:
        qs = qs.annotate(result_id=Cast("pk", CharField()))

    if query:
        qs = qs.annotate(
            rank=SearchRank(
                SearchVector("name", config="simple"), SearchQuery(query, config="simple", search_type="raw")
            )
        )
        qs = qs.filter(rank__gt=0.05)
        values.append("rank")

    qs = qs.values(*values)
    return qs, type
