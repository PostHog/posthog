import re
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from time import monotonic
from typing import Any, Literal, TypedDict, TypeVar, cast

from django.db import OperationalError, connection
from django.db.models import BigIntegerField, CharField, F, Model, QuerySet, Value
from django.db.models.functions import Cast, JSONObject
from django.http import HttpResponse

from drf_spectacular.utils import extend_schema
from prometheus_client import Counter
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.helpers.full_text_search import build_rank, process_query
from posthog.models import EventDefinition, PropertyDefinition
from posthog.models.utils import execute_with_timeout
from posthog.taxonomy.property_definition_api import is_query_canceled

from products.access_control.backend.facade.user_access_control import UserAccessControl, model_to_resource
from products.actions.backend.models.action import Action
from products.cohorts.backend.models.cohort import Cohort
from products.dashboards.backend.models.dashboard import Dashboard
from products.early_access_features.backend.models import EarlyAccessFeature
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.facade.models import Insight
from products.surveys.backend.models import Survey
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

LIMIT = 25

ENTITY_STATEMENT_TIMEOUT_MS = 3_000
"""`build_rank` composes the search vector over live columns instead of a stored tsvector, so no
index covers the rank predicate and each entity scans its whole project partition. This budget stops
one large entity from spending the whole request timeout."""

SEARCH_BUDGET_MS = 15_000
"""Ceiling on the entity queries together, so a project where many entities are slow still answers."""

SEARCH_TIMED_OUT_COUNTER = Counter(
    "project_search_entity_timed_out_total",
    "Project search entity queries cancelled by the per-entity statement timeout.",
    labelnames=["entity"],
)

T = TypeVar("T")


class EntityConfig(TypedDict, total=False):
    klass: type[Model]
    search_fields: dict[str, Literal["A", "B", "C"]]
    extra_fields: list[str]
    filters: dict[str, Any]


FEATURE_FLAG_SEARCH_CONFIG: EntityConfig = {
    "klass": FeatureFlag,
    "search_fields": {"key": "A", "name": "C"},
    "extra_fields": ["key", "name"],
    "filters": {"archived": False},
}


ENTITY_MAP: dict[str, EntityConfig] = {
    "insight": {
        "klass": Insight,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description", "query"],
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
    "feature_flag": FEATURE_FLAG_SEARCH_CONFIG,
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
    "property_definition": {
        "klass": PropertyDefinition,
        "search_fields": {"name": "A"},
        "extra_fields": ["name"],
    },
    "survey": {
        "klass": Survey,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description"],
    },
    "early_access_feature": {
        "klass": EarlyAccessFeature,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description"],
    },
    "hog_flow": {
        "klass": HogFlow,
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
    include_counts = serializers.BooleanField(required=False, default=True)

    def validate_q(self, value: str):
        # gracefully handle invalid queries
        if process_query(value) is None:
            return None
        return value


class SearchViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer

    @extend_schema(
        parameters=[QuerySerializer],
        description=(
            "Full-text search across project entities. Objects the user cannot access are left out. "
            "Each result includes `user_access_level`, the requesting user's resolved access level for "
            "that object; `null` when access controls don't apply to the entity type."
        ),
    )
    def list(self, request: Request, **kw) -> HttpResponse:
        # parse query params
        query_serializer = QuerySerializer(data=self.request.query_params)
        query_serializer.is_valid(raise_exception=True)
        params = query_serializer.validated_data

        # get entities to search from params or default to all entities
        entities = set(params["entities"]) if params["entities"] else set(ENTITY_MAP.keys())
        query = params["q"]
        include_counts = params["include_counts"]

        results, counts, _ = search_entities(
            entities,
            query,
            self.project_id,
            self,
            ENTITY_MAP,
            include_counts=include_counts,
            annotate_access_levels=self.user_access_control,
        )

        response_data: dict[str, Any] = {"results": results}
        if counts is not None:
            response_data["counts"] = counts
        return Response(response_data)


def search_entities(
    entities: set[str],
    query: str | None,
    project_id: int,
    view: TeamAndOrgViewSetMixin,
    entity_map: dict[str, EntityConfig],
    limit: int = LIMIT,
    offset: int = 0,
    include_counts: bool = True,
    annotate_access_levels: UserAccessControl | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int | None] | None, int | None]:
    """Search each entity separately, under its own time budget, and merge the pages here.

    Entities sharing one statement timeout would let the slowest of them decide whether the caller
    gets a result at all. Apart, a slow entity drops out — its count comes back as `None` — and the
    rest of the search still answers.
    """
    counts: dict[str, int | None] = dict.fromkeys(entity_map) if include_counts else {}
    # The merged page takes at most `cap` rows from any one entity, so the cap costs no results.
    cap = offset + limit
    rows: list[dict[str, Any]] = []
    deadline = monotonic() + SEARCH_BUDGET_MS / 1000
    order_by = "-rank" if query else F("_sort_name").asc(nulls_first=True)

    with _restored_statement_timeout():
        for entity in sorted(entities):  # sorted so equally ranked rows keep a stable order
            entity_meta = entity_map[entity]
            klass_qs, entity_name = class_queryset(
                view=view,
                klass=entity_meta["klass"],
                project_id=project_id,
                query=query,
                search_fields=entity_meta["search_fields"],
                extra_fields=entity_meta["extra_fields"],
                filters=entity_meta.get("filters"),
            )
            klass_qs = klass_qs.order_by(order_by)
            fetch_page: Callable[[], list[dict[str, Any]]] = partial(list, klass_qs[:cap])
            entity_rows = _run_bounded(entity_name, deadline, fetch_page)
            if entity_rows is None:
                continue
            rows.extend(entity_rows)
            if include_counts:
                # A short page is already the whole result set, so fetching it has done the count.
                counts[entity_name] = (
                    len(entity_rows) if len(entity_rows) < cap else _run_bounded(entity_name, deadline, klass_qs.count)
                )

    if query:
        rows.sort(key=lambda row: row["rank"], reverse=True)
    else:
        # Sort by type only. The name order is the database's, whose collation is not Python's, and
        # each entity's rows arrive contiguous, so a stable sort keeps the order the page was cut in.
        rows.sort(key=lambda row: row["type"])

    # The entities partition the rows, so their counts sum to the total without another scan.
    total_count = sum(count for count in counts.values() if count is not None) if include_counts else None

    results = cast(list[dict[str, Any]], rows[offset : offset + limit])
    if annotate_access_levels is not None:
        _annotate_user_access_levels(results, entity_map, annotate_access_levels)
    for result in results:
        result.pop("_sort_name", None)
        result.pop("_pk", None)
        result.pop("_created_by_id", None)
    return results, counts or None, total_count


def _run_bounded(entity: str, deadline: float, run: Callable[[], T]) -> T | None:
    """Returns `None` when the database cancels the query, or when the search has no budget left."""
    budget_ms = min(ENTITY_STATEMENT_TIMEOUT_MS, int((deadline - monotonic()) * 1000))
    if budget_ms <= 0:
        SEARCH_TIMED_OUT_COUNTER.labels(entity=entity).inc()
        return None
    try:
        with execute_with_timeout(budget_ms):
            return run()
    except OperationalError as error:
        if not is_query_canceled(error):
            raise
        SEARCH_TIMED_OUT_COUNTER.labels(entity=entity).inc()
        return None


@contextmanager
def _restored_statement_timeout() -> Iterator[None]:
    """Put the connection's `statement_timeout` back afterwards.

    `SET LOCAL` lasts until the enclosing transaction ends, so when the caller already holds one the
    per-entity budgets would otherwise govern every later query it runs.
    """
    if not connection.in_atomic_block:
        yield  # each per-entity transaction commits on its own, which discards its `SET LOCAL`
        return
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        row = cursor.fetchone()
    previous = row[0] if row else "0"
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = %s", [previous])


def _annotate_user_access_levels(
    results: list[dict[str, Any]],
    entity_map: dict[str, EntityConfig],
    user_access_control: UserAccessControl,
) -> None:
    """Set `user_access_level` on each result to the user's resolved level for that object
    ("none" means they can't open it), or None for entity types without access controls.

    Resolution is keyed by `_pk`, not `result_id` — insights and notebooks use short_id as
    their result_id while AccessControl rows are keyed by pk.
    """
    results_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        results_by_type[result["type"]].append(result)

    for entity_type, entity_results in results_by_type.items():
        resource = model_to_resource(cast(Model, entity_map[entity_type]["klass"]))
        if resource is None:
            for result in entity_results:
                result["user_access_level"] = None
            continue

        levels = user_access_control.bulk_object_access_levels(
            resource, [(result["_pk"], result["_created_by_id"]) for result in entity_results]
        )
        for result in entity_results:
            result["user_access_level"] = levels.get(result["_pk"])


def class_queryset(
    view: TeamAndOrgViewSetMixin,
    klass: type[Model],
    project_id: int,
    query: str | None,
    search_fields: dict[str, Literal["A", "B", "C"]],
    extra_fields: list[str] | None,
    filters: dict[str, Any] | None = None,
):
    """Builds a queryset for the class."""
    entity_type = class_to_entity_name(klass)
    values = ["type", "result_id", "extra_fields", "_sort_name", "_pk", "_created_by_id"]

    qs: QuerySet[Any] = cast(Any, klass).objects.filter(team__project_id=project_id)  # filter team
    qs = view.user_access_control.filter_queryset_by_access_level(qs)  # filter access level

    # Uniform columns for access level resolution — every entity must produce them
    qs = qs.annotate(_pk=Cast("pk", CharField()))
    if hasattr(klass, "created_by"):
        qs = qs.annotate(_created_by_id=F("created_by_id"))
    else:
        # Cast explicitly: Django renders an untyped None as a bare `NULL`, which Postgres types
        # as `text` rather than the integer `_created_by_id` readers expect.
        qs = qs.annotate(_created_by_id=Cast(Value(None), output_field=BigIntegerField()))

    # Apply entity-specific filters
    if filters:
        qs = qs.filter(**filters)

    # :TRICKY: can't use an annotation here as `type` conflicts with a field on some models
    # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (entity_type from code-controlled model class names)
    qs = qs.extra(select={"type": f"'{entity_type}'"})  # entity type

    # entity id
    if entity_type == "insight" or entity_type == "notebook":
        qs = qs.annotate(result_id=F("short_id"))
    else:
        qs = qs.annotate(result_id=Cast("pk", CharField()))

    # Exclude generated dashboards
    if entity_type == "dashboard":
        qs = qs.exclude(creation_mode="template")

    # extra fields
    if extra_fields:
        qs = qs.annotate(extra_fields=JSONObject(**{field: field for field in extra_fields}))
    else:
        qs = qs.annotate(extra_fields=JSONObject())

    sort_field: str | None = None
    if extra_fields and "name" in extra_fields:
        sort_field = "name"
    elif entity_type == "notebook":
        sort_field = "title"

    if sort_field:
        qs = qs.annotate(_sort_name=F(sort_field))
    else:
        qs = qs.annotate(_sort_name=Value(None, output_field=CharField()))

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
