import functools
import re
from typing import Any
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import Model, Value, CharField, F, QuerySet
from django.db.models.functions import Cast, JSONObject
from django.http import HttpResponse
from rest_framework import viewsets, serializers
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Action, Cohort, Insight, Dashboard, FeatureFlag, Experiment, EventDefinition, Survey
from posthog.models.notebook.notebook import Notebook

LIMIT = 25


ENTITY_MAP = {
    "insight": {
        "klass": Insight,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description", "filters", "query"],
    },
    "dashboard": {
        "klass": Dashboard,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description"],
    },
    "experiment": {
        "klass": Experiment,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description"],
    },
    "feature_flag": {"klass": FeatureFlag, "search_fields": {"key": "A", "name": "C"}, "extra_fields": ["key", "name"]},
    "notebook": {
        "klass": Notebook,
        "search_fields": {"title": "A", "text_content": "C"},
        "extra_fields": ["title", "content"],
    },
    "action": {
        "klass": Action,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description"],
    },
    "cohort": {
        "klass": Cohort,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description"],
    },
    "event_definition": {
        "klass": EventDefinition,
        "search_fields": {"name": "A"},
        "extra_fields": ["name"],
    },
    "survey": {
        "klass": Survey,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description"],
    },
}
"""
Map of entity names to their class, search_fields and extra_fields.

The value in search_fields corresponds to the PostgreSQL weighting i.e. A, B, C or D.
"""


class QuerySerializer(serializers.Serializer):
    """Validates and formats query params."""

    q = serializers.CharField(required=False, default="")
    entities = serializers.MultipleChoiceField(required=False, choices=list(ENTITY_MAP.keys()))

    def validate_q(self, value: str):
        return process_query(value)


class SearchViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    def list(self, request: Request, **kw) -> HttpResponse:
        # parse query params
        query_serializer = QuerySerializer(data=self.request.query_params)
        query_serializer.is_valid(raise_exception=True)
        params = query_serializer.validated_data

        counts = {key: None for key in ENTITY_MAP}
        # get entities to search from params or default to all entities
        entities = params["entities"] if len(params["entities"]) > 0 else set(ENTITY_MAP.keys())
        query = params["q"]

        # empty queryset to union things onto it
        qs = (
            Dashboard.objects.annotate(type=Value("empty", output_field=CharField()))
            .filter(team__project_id=self.project_id)
            .none()
        )

        # add entities
        for entity_meta in [ENTITY_MAP[entity] for entity in entities]:
            klass_qs, entity_name = class_queryset(
                view=self,
                klass=entity_meta.get("klass"),
                project_id=self.project_id,
                query=query,
                search_fields=entity_meta.get("search_fields"),
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
    view: TeamAndOrgViewSetMixin,
    klass: type[Model],
    project_id: int,
    query: str | None,
    search_fields: dict[str, str],
    extra_fields: dict | None,
):
    """Builds a queryset for the class."""
    entity_type = class_to_entity_name(klass)
    values = ["type", "result_id", "extra_fields"]

    qs: QuerySet[Any] = klass.objects.filter(team__project_id=project_id)  # filter team
    qs = view.user_access_control.filter_queryset_by_access_level(qs)  # filter access level

    # :TRICKY: can't use an annotation here as `type` conflicts with a field on some models
    qs = qs.extra(select={"type": f"'{entity_type}'"})  # entity type

    # entity id
    if entity_type == "insight" or entity_type == "notebook":
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
        search_vectors = [SearchVector(key, weight=value, config="simple") for key, value in search_fields.items()]
        combined_vector = functools.reduce(lambda a, b: a + b, search_vectors)
        qs = qs.annotate(
            rank=SearchRank(combined_vector, SearchQuery(query, config="simple", search_type="raw")),
        )
        qs = qs.filter(rank__gt=0.05)
        values.append("rank")
        qs.annotate(rank=F("rank"))

    # specify fields to fetch
    qs = qs.values(*values)

    return qs, entity_type


def class_to_entity_name(klass: type[Model]):
    """Converts the class name to snake case."""
    return re.sub("(?!^)([A-Z]+)", r"_\1", klass.__name__).lower()
