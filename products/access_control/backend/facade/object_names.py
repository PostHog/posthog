"""Which model backs each access-controlled resource, and how its objects are named.

The registry (`resources_with_object_access_controls`) walks the registered routes, so it cannot
drift from the code: a viewset opts in by mixing in AccessControlViewSetMixin, which stamps the
`object_access_controls` marker this module keys on. The naming helpers build the display names
the settings UI and the resolution preview show for object rules.
"""

from dataclasses import dataclass
from functools import cache
from typing import cast

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Model
from django.urls import URLResolver, get_resolver

from posthog.exceptions_capture import capture_exception
from posthog.scopes import INTERNAL_API_SCOPE_OBJECTS, APIScopeObject


@dataclass(frozen=True, kw_only=True)
class _ResourceDisplayModel:
    app_label: str
    model_name: str
    name_field: str


# Names come from universal search's ENTITY_MAP first; these entries cover resources search doesn't
# index, so they have no ENTITY_MAP entry to borrow. Add one when a resource's objects render raw
# ids instead of names, in the rules list or the picker; delete one when search starts indexing the
# resource, since ENTITY_MAP is consulted first and the entry goes dead. A resource in neither place
# and with no derivable name field is left out of the picker and falls back to the raw id.
_MODELS_NOT_IN_ENTITY_MAP: dict[str, _ResourceDisplayModel] = {
    "evaluation": _ResourceDisplayModel(app_label="ai_observability", model_name="evaluation", name_field="name"),
    "warehouse_view": _ResourceDisplayModel(
        app_label="data_modeling", model_name="datawarehousesavedquery", name_field="name"
    ),
    "warehouse_table": _ResourceDisplayModel(
        app_label="warehouse_sources", model_name="datawarehousetable", name_field="name"
    ),
    "external_data_source": _ResourceDisplayModel(
        app_label="warehouse_sources", model_name="externaldatasource", name_field="source_type"
    ),
    "session_recording": _ResourceDisplayModel(
        app_label="posthog", model_name="sessionrecording", name_field="session_id"
    ),
    "ticket": _ResourceDisplayModel(app_label="conversations", model_name="ticket", name_field="ticket_number"),
}


@dataclass(frozen=True, kw_only=True)
class ResolvedObjectName:
    name: str | None
    # Insights link by short_id rather than pk, so the frontend needs it alongside the name
    short_id: str | None = None


@cache
def resources_with_object_access_controls() -> dict[APIScopeObject, frozenset[type[Model]]]:
    """Resources that support object-level access controls, mapped to the models behind them.

    A viewset opts in by mixing in AccessControlViewSetMixin, so the registered routes are the
    source of truth and this cannot drift from the code; adding the mixin also puts the resource in
    the settings picker. A scope served by several viewsets maps to several models. The snapshot
    test in test_access_control.py records the resources; regenerate it with `pytest
    --snapshot-update`.
    """
    found: dict[APIScopeObject, set[type[Model]]] = {}

    def walk(resolver: URLResolver) -> None:
        for pattern in resolver.url_patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern)
                continue
            cls = getattr(pattern.callback, "cls", None)
            # The marker AccessControlViewSetMixin stamps, so this facade module needs no
            # import of the presentation class
            if cls is None or not getattr(cls, "object_access_controls", False):
                continue
            scope = getattr(cls, "scope_object", None)
            # Project-level access is its own control (the "Project access" dropdown), never an
            # object rule; every rules endpoint filters resource="project" out as well
            if scope and scope != "INTERNAL" and scope != "project" and scope not in INTERNAL_API_SCOPE_OBJECTS:
                queryset = getattr(cls, "queryset", None)
                found.setdefault(scope, set())
                if queryset is not None:
                    found[scope].add(queryset.model)

    walk(get_resolver())
    return {scope: frozenset(models) for scope, models in found.items()}


def model_has_field(model: type[Model], field: str) -> bool:
    try:
        model._meta.get_field(field)
        return True
    except FieldDoesNotExist:
        return False


@dataclass(frozen=True, kw_only=True)
class DisplayModel:
    """Where a resource's objects live and which field names them."""

    model: type[Model]
    name_field: str


def display_model(resource: str) -> DisplayModel | None:
    """Resolve a resource to its model and display field. None means the settings UI cannot work
    with the resource's objects: search returns 400, rule writes return 400, existing rules show
    raw ids.

    A resource qualifies when its viewsets carry object-level access controls and we can name its
    objects, tried in order: search's ENTITY_MAP (its rank-A field is the display name), the
    supplement for resources search doesn't index, and finally a resource whose routes expose
    exactly one model carrying a recognizable name field.
    """
    # Gate before the cached resolver: resource is raw request input, and caching unknown values
    # would grow the cache by one permanent entry per distinct garbage string
    if resource not in resources_with_object_access_controls():
        return None
    return _display_model_for_known_resource(resource)


@cache
def _display_model_for_known_resource(resource: str) -> DisplayModel | None:
    from posthog.api.search import (
        ENTITY_MAP,  # noqa: PLC0415 — imports every searchable product model, keep it off this module's import path
    )

    model: type[Model] | None = None
    name_field: str | None = None
    entity = ENTITY_MAP.get(resource)
    supplement = _MODELS_NOT_IN_ENTITY_MAP.get(resource)
    if entity is not None:
        model = entity["klass"]
        name_field = next((field for field, rank in entity["search_fields"].items() if rank == "A"), None)
    elif supplement is not None:
        model = apps.get_model(supplement.app_label, supplement.model_name)
        name_field = supplement.name_field
    else:
        models = resources_with_object_access_controls().get(cast(APIScopeObject, resource)) or frozenset()
        if len(models) == 1:
            model = next(iter(models))
            name_field = next((field for field in ("name", "title", "key") if model_has_field(model, field)), None)

    if model is None or name_field is None or not model_has_field(model, "team"):
        return None
    return DisplayModel(model=model, name_field=name_field)


def resolve_object_names(resource: str, resource_ids: list[str], team_id: int) -> dict[str, ResolvedObjectName]:
    """Map {resource_id -> display info} for one resource type, empty when we can't name its objects.

    Queries through _base_manager so rules pointing at soft-deleted objects still resolve: those are
    exactly the rows someone opens this page to clean up. Tenant isolation holds via team_id.
    """
    display = display_model(resource) if resource_ids else None
    if display is None:
        return {}
    try:
        rows = display.model._base_manager.filter(team_id=team_id, pk__in=resource_ids)
        if resource == "insight":
            # Insight.name is nullable and saved insights often carry only derived_name, and insight
            # URLs address short_ids rather than the pk rules store
            return {
                str(pk): ResolvedObjectName(name=name or derived_name, short_id=short_id)
                for pk, name, derived_name, short_id in rows.values_list("pk", "name", "derived_name", "short_id")
            }
        if resource == "ticket":
            # A bare number doesn't read as an object; match the ticket page's own title
            return {
                str(pk): ResolvedObjectName(name=f"Ticket: {number}")
                for pk, number in rows.values_list("pk", "ticket_number")
            }
        if model_has_field(display.model, "short_id"):
            # Notebooks and other short_id models link by short_id, like insights
            return {
                str(pk): ResolvedObjectName(name=name, short_id=short_id)
                for pk, name, short_id in rows.values_list("pk", display.name_field, "short_id")
            }
        return {str(pk): ResolvedObjectName(name=name) for pk, name in rows.values_list("pk", display.name_field)}
    except Exception as e:
        # A resource_id of the wrong shape for the model's pk, or a model that moved. The rules list
        # falls back to raw ids, but report it: one failure usually breaks the whole resource type
        capture_exception(e, {"resource": resource})
        return {}
