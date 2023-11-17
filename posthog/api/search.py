import re
from typing import Any
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import Model, Value, CharField, F, QuerySet
from django.db.models.functions import Cast, JSONObject
from django.http import HttpResponse
from rest_framework import viewsets, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.models import Action, Cohort, Insight, Dashboard, FeatureFlag, Experiment, Team

LIMIT = 25


ENTITY_MAP = {
    "action": {"klass": Action},
    "cohort": {"klass": Cohort},
    "insight": {"klass": Insight, "extra_fields": ["derived_name"]},
    "dashboard": {"klass": Dashboard},
    "experiment": {"klass": Experiment},
    "feature_flag": {"klass": FeatureFlag},
}


class QuerySerializer(serializers.Serializer):
    """Validates and formats query params."""

    q = serializers.CharField(required=False, default="")
    entities = serializers.MultipleChoiceField(required=False, choices=list(ENTITY_MAP.keys()))

    def validate_q(self, value: str):
        return process_query(value)


class SearchViewSet(StructuredViewSetMixin, viewsets.ViewSet):
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    def list(self, request: Request, **kw) -> HttpResponse:
        # parse query params
        query_serializer = QuerySerializer(data=self.request.query_params)
        query_serializer.is_valid(raise_exception=True)
        params = query_serializer.validated_data

        counts = {}
        # get entities to search from params or default to all entities
        entities = params["entities"] if len(params["entities"]) > 0 else set(ENTITY_MAP.keys())
        query = params["q"]

        # empty queryset to union things onto it
        qs = Dashboard.objects.annotate(type=Value("empty", output_field=CharField())).filter(team=self.team).none()

        # add entities
        for entity_meta in [ENTITY_MAP[entity] for entity in entities]:
            klass_qs, entity_name = class_queryset(
                klass=entity_meta.get("klass"),
                team=self.team,
                query=query,
                extra_fields=entity_meta.get("extra_fields"),
            )
            qs = qs.union(klass_qs)
            counts[entity_name] = klass_qs.count()

        # order by rank
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


def class_queryset(
    klass: type[Model],
    team: Team,
    query: str | None,
    extra_fields: dict | None,
):
    """Builds a queryset for the class."""
    entity_type = class_to_entity_name(klass)
    values = ["type", "result_id", "name", "extra_fields"]

    qs: QuerySet[Any] = klass.objects.filter(team=team)  # filter team
    qs = qs.annotate(type=Value(entity_type, output_field=CharField()))  # entity type

    # entity id
    if entity_type == "insight":
        qs = qs.annotate(result_id=F("short_id"))
    else:
        qs = qs.annotate(result_id=Cast("pk", CharField()))

    # extra fields
    if extra_fields:
        qs = qs.annotate(extra_fields=JSONObject(**{field: field for field in extra_fields}))
    else:
        qs = qs.annotate(extra_fields=JSONObject())

    # full-text search rank
    if query:
        qs = qs.annotate(
            rank=SearchRank(
                SearchVector("name", config="simple"), SearchQuery(query, config="simple", search_type="raw")
            ),
        )
        qs = qs.filter(rank__gt=0.05)
        values.append("rank")

    # specify fields to fetch
    qs = qs.values(*values)

    return qs, entity_type


def class_to_entity_name(klass: type[Model]):
    """Converts the class name to snake case."""
    return re.sub("(?!^)([A-Z]+)", r"_\1", klass.__name__).lower()
