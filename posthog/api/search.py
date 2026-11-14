import re
import operator
from collections import defaultdict
from collections.abc import Mapping
from functools import partial, reduce
from typing import Any, Literal, Protocol, TypedDict, cast

from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import BigIntegerField, CharField, F, Model, OuterRef, Q, QuerySet, Subquery, Value
from django.db.models.functions import Cast, JSONObject
from django.db.models.lookups import Contains
from django.http import HttpResponse

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.helpers.full_text_search import build_rank, process_query
from posthog.models.team import Team
from posthog.models.user import User
from posthog.oauth_provenance import is_sandbox_oauth_request

from products.access_control.backend.facade.user_access_control import UserAccessControl, model_to_resource
from products.actions.backend.facade.api import search_actions
from products.canvas.backend.facade.contracts import CanvasViewer
from products.canvas.backend.facade.search import search_canvases
from products.cohorts.backend.models.cohort import Cohort
from products.dashboards.backend.facade.api import search_dashboards
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery, Node
from products.early_access_features.backend.models import EarlyAccessFeature
from products.endpoints.backend.facade.models import Endpoint
from products.event_definitions.backend.models import EventDefinition, PropertyDefinition
from products.event_definitions.backend.models.property_definition import effective_project_id_expr
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.facade.models import Insight
from products.surveys.backend.models import Survey
from products.workflows.backend.facade.api import search_workflows

LIMIT = 25


class _PostgresILikeContains(Contains):
    def get_rhs_op(self, connection: BaseDatabaseWrapper, rhs: str) -> str:
        return f"ILIKE {rhs}"


class EntityConfig(TypedDict, total=False):
    klass: type[Model]
    search_fields: dict[str, Literal["A", "B", "C"]]
    extra_fields: list[str]
    annotations: dict[str, Any]
    filters: dict[str, Any]
    excludes: list[dict[str, Any]]


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
    "data_warehouse_view": {
        "klass": DataWarehouseSavedQuery,
        "search_fields": {"name": "A"},
        "extra_fields": ["name", "node_id"],
        "annotations": {
            "node_id": Subquery(Node.objects.filter(saved_query_id=OuterRef("pk")).order_by("id").values("id")[:1])
        },
        "filters": {
            "is_test": False,
            "managed_viewset__isnull": True,
            "node_id__isnull": False,
        },
        "excludes": [
            {"deleted": True},
            {
                "origin__in": [
                    DataWarehouseSavedQuery.Origin.ENDPOINT,
                    DataWarehouseSavedQuery.Origin.MANAGED_VIEWSET,
                ]
            },
        ],
    },
    "endpoint": {
        "klass": Endpoint,
        "search_fields": {"name": "A"},
        "extra_fields": ["name"],
        "excludes": [{"deleted": True}],
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
}


class FacadeSearch(Protocol):
    """A product facade's search, returning results in the shape of a union row, and the total."""

    def __call__(
        self,
        *,
        project_id: int,
        query: str | None,
        access_control: UserAccessControl,
        limit: int,
        with_access_levels: bool,
        include_count: bool,
    ) -> tuple[list[dict[str, Any]], int]: ...


def _search_actions(**kwargs: Any) -> tuple[list[dict[str, Any]], int]:
    return search_actions(include_deleted=True, **kwargs)


def search_live_actions(**kwargs: Any) -> tuple[list[dict[str, Any]], int]:
    """The action search for a caller that leaves soft-deleted actions out."""
    return search_actions(include_deleted=False, **kwargs)


def _search_workflows(**kwargs: Any) -> tuple[list[dict[str, Any]], int]:
    results, count = search_workflows(include_archived=True, **kwargs)
    for result in results:
        result["extra_fields"].pop("status", None)
    return results, count


# Actions, dashboards and workflows are searched through their products' facades rather than unioned by model
# class, so they are not in ENTITY_MAP. `search_entities` merges them in when one is requested.
ACTION_ENTITY = "action"
DASHBOARD_ENTITY = "dashboard"
WORKFLOW_ENTITY = "hog_flow"
CANVAS_ENTITY = "canvas"
FACADE_SEARCHES: dict[str, FacadeSearch] = {
    DASHBOARD_ENTITY: search_dashboards,
    ACTION_ENTITY: _search_actions,
    WORKFLOW_ENTITY: _search_workflows,
    CANVAS_ENTITY: search_canvases,
}
# Actions keep their place between notebooks and cohorts in the entity choices and the counts.
_UNION_ENTITY_NAMES = [*ENTITY_MAP]
_DASHBOARD_SLOT = _UNION_ENTITY_NAMES.index("insight") + 1
_ACTION_SLOT = _UNION_ENTITY_NAMES.index("cohort")
_COUNTED_ENTITIES = [
    *_UNION_ENTITY_NAMES[:_DASHBOARD_SLOT],
    DASHBOARD_ENTITY,
    *_UNION_ENTITY_NAMES[_DASHBOARD_SLOT:_ACTION_SLOT],
    ACTION_ENTITY,
    *_UNION_ENTITY_NAMES[_ACTION_SLOT:],
]
SEARCHABLE_ENTITIES = [*_COUNTED_ENTITIES, WORKFLOW_ENTITY, CANVAS_ENTITY]
"""
Map of entity names to their class, search_fields and extra_fields.

The value in search_fields corresponds to the PostgreSQL weighting i.e. A, B, C or D.
"""


class QuerySerializer(serializers.Serializer):
    """Validates and formats query params."""

    q = serializers.CharField(required=False, default="")
    entities = serializers.MultipleChoiceField(required=False, choices=SEARCHABLE_ENTITIES)
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
        entities = set(params["entities"]) if params["entities"] else set(SEARCHABLE_ENTITIES)
        query = params["q"]
        include_counts = params["include_counts"]

        user = request.user
        # A sandbox token with no task binding reaches no canvas, so agents never search the user's spaces.
        canvas_viewer = CanvasViewer(
            team_id=self.team_id,
            user_id=user.id if isinstance(user, User) else None,
            sandboxed=is_sandbox_oauth_request(request),
            sandbox_task_id=None,
        )

        results, counts, _ = search_entities(
            entities,
            query,
            self.project_id,
            self,
            ENTITY_MAP,
            facade_searches={**FACADE_SEARCHES, CANVAS_ENTITY: partial(search_canvases, viewer=canvas_viewer)},
            include_counts=include_counts,
            annotate_access_levels=self.user_access_control,
            counted_entities=_COUNTED_ENTITIES,
        )

        response_data: dict[str, Any] = {"results": results}
        if counts is not None:
            counts.setdefault(WORKFLOW_ENTITY, None)
            counts.setdefault(CANVAS_ENTITY, None)
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
    facade_searches: Mapping[str, FacadeSearch] = FACADE_SEARCHES,
    counted_entities: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int | None] | None, int | None]:
    """Search the requested entities: those in `entity_map` in one SQL union, those in `facade_searches`
    through their products' facades, merged into one ranked page.

    `counted_entities` names the keys `counts` starts with, in order, each None until searched. It
    defaults to the `entity_map` keys.
    """
    requested_facades = [name for name in facade_searches if name in entities]
    entities = entities - set(facade_searches)

    # empty queryset to union things onto it
    counts: dict[str, int | None] = (
        dict.fromkeys(counted_entities if counted_entities is not None else entity_map) if include_counts else {}
    )
    qs: QuerySet[Any] = Team.objects.none()

    # add entities
    for entity_type in sorted(entities):
        entity_meta = entity_map[entity_type]
        assert entity_meta is not None
        klass_qs, entity_name = class_queryset(
            view=view,
            klass=entity_meta["klass"],
            project_id=project_id,
            query=query,
            search_fields=entity_meta["search_fields"],
            extra_fields=entity_meta["extra_fields"],
            entity_type=entity_type,
            annotations=entity_meta.get("annotations"),
            filters=entity_meta.get("filters"),
            excludes=entity_meta.get("excludes"),
        )
        qs = qs.union(klass_qs)
        if include_counts:
            counts[entity_name] = klass_qs.count()

    # order by rank. Ordering an empty union by a column no member added raises, which only
    # happens here when facade-searched entities were the only ones requested.
    if entities or not requested_facades:
        if query:
            qs = qs.order_by(F("rank").desc())
        else:
            qs = qs.order_by("type", F("_sort_name").asc(nulls_first=True))

    if not requested_facades:
        # Get total count before pagination (only when needed)
        total_count = qs.count() if include_counts else None
        results = cast(list[dict[str, Any]], list(qs[offset : offset + limit]))
        if annotate_access_levels is not None:
            _annotate_user_access_levels(results, entity_map, annotate_access_levels)
    else:
        facade_results: list[dict[str, Any]] = []
        facade_count = 0
        for name in requested_facades:
            # Each source returns its first offset + limit rows, so the merged page is complete.
            name_results, name_count = facade_searches[name](
                project_id=project_id,
                query=query,
                access_control=view.user_access_control,
                limit=offset + limit,
                with_access_levels=annotate_access_levels is not None,
                include_count=include_counts,
            )
            facade_results.extend(name_results)
            facade_count += name_count
            if include_counts:
                counts[name] = name_count

        union_results = cast(list[dict[str, Any]], list(qs[: offset + limit])) if entities else []
        if annotate_access_levels is not None:
            _annotate_user_access_levels(union_results, entity_map, annotate_access_levels)
        total_count = ((qs.count() if entities else 0) + facade_count) if include_counts else None

        # Every input arrives in the database order, so a stable sort on the leading key keeps it.
        merged = [*union_results, *facade_results]
        if query:
            merged.sort(key=lambda result: result["rank"], reverse=True)
        else:
            merged.sort(key=lambda result: result["type"])
        results = merged[offset : offset + limit]

    for result in results:
        result.pop("_sort_name", None)
        result.pop("_pk", None)
        result.pop("_created_by_id", None)
    return results, counts or None, total_count


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
    entity_type: str | None = None,
    annotations: dict[str, Any] | None = None,
    filters: dict[str, Any] | None = None,
    excludes: list[dict[str, Any]] | None = None,
):
    """Builds a queryset for the class."""
    entity_type = entity_type or class_to_entity_name(klass)
    values = ["type", "result_id", "extra_fields", "_sort_name", "_pk", "_created_by_id"]

    qs: QuerySet[Any]
    if klass in (EventDefinition, PropertyDefinition):
        # A join on team would bypass the project-leading unique index on these large tables.
        qs = (
            cast(Any, klass)
            .objects.alias(effective_project_id=effective_project_id_expr())
            .filter(effective_project_id=project_id)
        )
    else:
        qs = cast(Any, klass).objects.filter(team__project_id=project_id)  # filter team
    qs = view.user_access_control.filter_queryset_by_access_level(qs)  # filter access level

    if annotations:
        qs = qs.annotate(**annotations)

    # Uniform columns for access level resolution — every union member must produce them
    qs = qs.annotate(_pk=Cast("pk", CharField()))
    if hasattr(klass, "created_by"):
        qs = qs.annotate(_created_by_id=F("created_by_id"))
    else:
        # Explicitly cast rather than relying on Value(None, ...)'s output_field: Django
        # renders untyped None values as a bare `NULL`, so if two or more such entities end
        # up adjacent in the union, Postgres resolves their shared column as `text` and then
        # fails to match it against a real integer `_created_by_id` column elsewhere.
        qs = qs.annotate(_created_by_id=Cast(Value(None), output_field=BigIntegerField()))

    # Apply entity-specific filters
    if filters:
        qs = qs.filter(**filters)
    if excludes:
        for exclude in excludes:
            qs = qs.exclude(**exclude)

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
        if klass in (EventDefinition, PropertyDefinition):
            words = re.findall(r"[^\W_]+", query)
            if words:
                qs = qs.filter(reduce(operator.or_, (Q(_PostgresILikeContains(F("name"), word)) for word in words)))
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
