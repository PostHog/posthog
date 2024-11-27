import re
from typing import Any, Literal, TypedDict
from django.db.models import Model, Value, CharField, F, QuerySet
from django.db.models.functions import Cast, JSONObject
from django.http import HttpResponse
from rest_framework import viewsets, serializers
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.helpers.full_text_search import build_rank, process_query
from posthog.models import Action, Cohort, Insight, Dashboard, FeatureFlag, Experiment, EventDefinition, Survey
from posthog.models.notebook.notebook import Notebook

LIMIT = 25


class EntityConfig(TypedDict):
    klass: type[Model]
    search_fields: dict[str, Literal["A", "B", "C"]]
    extra_fields: list[str]


ENTITY_MAP: dict[str, EntityConfig] = {
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
        # gracefully handle invalid queries
        if process_query(value) is None:
            return None
        return value


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
            assert entity_meta is not None
            klass_qs, entity_name = class_queryset(
                view=self,
                klass=entity_meta["klass"],
                project_id=self.project_id,
                query=query,
                search_fields=entity_meta["search_fields"],
                extra_fields=entity_meta["extra_fields"],
            )
            qs = qs.union(klass_qs)
            counts[entity_name] = klass_qs.count()

        # order by rank
        if query:
            qs = qs.order_by("-rank")

        return Response({"results": qs[:LIMIT], "counts": counts})


def class_queryset(
    view: TeamAndOrgViewSetMixin,
    klass: type[Model],
    project_id: int,
    query: str | None,
    search_fields: dict[str, Literal["A", "B", "C"]],
    extra_fields: list[str] | None,
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
        qs = qs.annotate(rank=build_rank(search_fields, query, config="simple"))
        qs = qs.filter(rank__gt=0.05)
        values.append("rank")
        qs.annotate(rank=F("rank"))

    # specify fields to fetch
    qs = qs.values(*values)

    return qs, entity_type


def class_to_entity_name(klass: type[Model]):
    """Converts the class name to snake case."""
    return re.sub("(?!^)([A-Z]+)", r"_\1", klass.__name__).lower()
