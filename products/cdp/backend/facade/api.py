"""
Facade for cdp.

Re-exports the HogFunction serializer cross-product API views reuse, and the action access
checks that need DRF. Lazy (PEP 562) to keep the DRF/serializer import chain off config-only
import paths.
"""

from __future__ import annotations

import operator
from collections.abc import Collection, Mapping, Sequence
from copy import deepcopy
from functools import reduce
from typing import Any, cast
from uuid import UUID

from django.db import transaction
from django.db.models import Q, QuerySet

from posthog.hogql import ast

from posthog.models.team import Team
from posthog.models.user import User
from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers

from products.cdp.backend.flag_gated_templates import FLAG_GATED_TEMPLATE_IDS, gated_template_enabled
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions import HogFunction

_B = "products.cdp.backend."

_LAZY = {
    "HogFunctionFiltersSerializer": "presentation.serializers",
    "HogFunctionSerializer": "api.hog_function",
    "action_ids_in_filters": "validation",
    "compile_hog": "validation",
    "require_viewer_access_to_actions": "validation",
}

__all__ = [
    *sorted(_LAZY),
    "compile_filters_expr",
    "create_hog_functions",
    "disable_managed_hog_functions",
    "filter_property_references",
    "has_enabled_hog_function_for_warehouse_table",
    "is_hog_function_template_available",
    "upsert_managed_hog_function",
    "warehouse_tables_with_enabled_hog_functions",
]


def is_hog_function_template_available(template_id: str, team: Team) -> bool:
    if HogFunctionTemplate.get_template(template_id) is None:
        return False
    flag = FLAG_GATED_TEMPLATE_IDS.get(template_id)
    return flag is None or gated_template_enabled(flag, team)


def create_hog_functions(
    payloads: Sequence[dict[str, Any]],
    *,
    team_id: int,
    created_by_id: int,
    allow_managed_alert_destination: bool,
) -> list[UUID]:
    """Create one hog function per payload and return their ids in the order given.

    Callers outside this product have no DRF request to take an acting user from, so the
    acting user comes in as an id. The team and the acting user are resolved once for the
    whole batch, so a caller writing several functions still pays two point lookups.
    """
    # Same reason as _LAZY below: the serializer drags DRF, so it stays off this module's
    # import path.
    from products.cdp.backend.api.hog_function import HogFunctionSerializer  # noqa: PLC0415

    team = Team.objects.get(id=team_id)
    created_by = User.objects.get(id=created_by_id)
    created_ids: list[UUID] = []
    for payload in payloads:
        serializer = HogFunctionSerializer(
            data=payload,
            context={
                "get_team": lambda: team,
                "is_create": True,
                "allow_managed_alert_destination": allow_managed_alert_destination,
            },
        )
        serializer.is_valid(raise_exception=True)
        created_ids.append(serializer.save(team=team, created_by=created_by).id)
    return created_ids


def upsert_managed_hog_function(
    payload: Mapping[str, Any],
    *,
    team_id: int,
    created_by_id: int,
    managed_by: str,
    hog_function_id: UUID | None = None,
) -> UUID:
    """Create a hog function owned by `managed_by`, or update one it already owns.

    The public hog function API hides owned functions and refuses to change them. An update of a
    function that another product owns, or that no product owns, raises PermissionDenied.
    Updates preserve the worker's automatically disabled state.
    """
    from products.cdp.backend.api.hog_function import HogFunctionSerializer  # noqa: PLC0415

    team = Team.objects.get(id=team_id)
    instance = HogFunction.objects.get(team_id=team_id, id=hog_function_id) if hog_function_id else None
    serializer = HogFunctionSerializer(
        instance=instance,
        data=dict(payload),
        partial=instance is not None,
        context={"get_team": lambda: team, "is_create": instance is None, "managed_by": managed_by},
    )
    serializer.is_valid(raise_exception=True)
    if instance is not None:
        saved = serializer.save(team=team)
    else:
        saved = serializer.save(team=team, created_by=User.objects.get(id=created_by_id))
    saved_id = cast(HogFunction, saved).id
    # The post_save reload fires inside the caller's transaction, before the workers can read the row.
    transaction.on_commit(
        lambda: reload_hog_functions_on_workers(team_id=team_id, hog_function_ids=[str(saved_id)]), robust=True
    )
    return saved_id


def disable_managed_hog_functions(*, team_id: int, managed_by: str, hog_function_ids: Sequence[UUID]) -> None:
    """Disable the given functions that `managed_by` owns and drop their secret inputs."""
    functions = HogFunction.objects.filter(team_id=team_id, managed_by=managed_by, id__in=hog_function_ids)
    disabled_ids = [str(pk) for pk in functions.values_list("id", flat=True)]
    if not disabled_ids:
        return
    # A queryset update skips the post_save receiver, so the workers are told here.
    functions.update(enabled=False, encrypted_inputs=None)
    transaction.on_commit(
        lambda: reload_hog_functions_on_workers(team_id=team_id, hog_function_ids=disabled_ids), robust=True
    )


def compile_filters_expr(filters: Mapping[str, Any], *, team_id: int) -> ast.Expr:
    """The HogQL expression a hog function's filters compile to."""
    # filters pulls in posthog.schema, which must stay off django.setup().
    from products.cdp.backend.filters import compile_filters_expr as _compile_filters_expr  # noqa: PLC0415

    return _compile_filters_expr(deepcopy(dict(filters)), Team.objects.get(id=team_id))


def filter_property_references(filters: Mapping[str, Any], *, team_id: int) -> dict[str, list[str | None]]:
    """The properties a hog function's filters read, keyed by "event", "person" or "group:<index>".

    A None name means the filters read the whole properties object of that scope. Nothing is stored.
    """
    # filters pulls in posthog.schema, which must stay off django.setup().
    from products.cdp.backend.filters import filter_property_references as _filter_property_references  # noqa: PLC0415

    return _filter_property_references(deepcopy(dict(filters)), Team.objects.get(id=team_id))


def _enabled_hog_functions_triggered_by(
    team_id: int, trigger_source: str, table_names: Collection[str]
) -> QuerySet[HogFunction]:
    names_any_table = reduce(
        operator.or_, (Q(filters__data_warehouse__contains=[{"table_name": name}]) for name in table_names)
    )
    return (
        HogFunction.objects.filter(team_id=team_id, enabled=True, filters__source=trigger_source)
        .filter(names_any_table)
        .exclude(deleted=True)
    )


def has_enabled_hog_function_for_warehouse_table(*, team_id: int, trigger_source: str, table_name: str) -> bool:
    """Whether an enabled hog function triggers on this warehouse table."""
    return _enabled_hog_functions_triggered_by(team_id, trigger_source, [table_name]).exists()


def warehouse_tables_with_enabled_hog_functions(
    *, team_id: int, trigger_source: str, table_names: Collection[str]
) -> set[str]:
    """The given warehouse table names that an enabled hog function triggers on."""
    names = set(table_names)
    if not names:
        return set()
    triggering_filters = _enabled_hog_functions_triggered_by(team_id, trigger_source, names).values_list(
        "filters", flat=True
    )
    return {
        table["table_name"]
        for filters in triggering_filters
        for table in (filters or {}).get("data_warehouse") or []
        if isinstance(table, dict) and isinstance(table.get("table_name"), str) and table["table_name"] in names
    }


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)
