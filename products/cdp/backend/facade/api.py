"""
Facade for cdp.

Re-exports the HogFunction serializer cross-product API views reuse. Lazy (PEP 562) to
keep the DRF/serializer import chain off config-only import paths.
"""

from __future__ import annotations

import json
import operator
from collections.abc import Collection, Sequence
from datetime import datetime
from functools import reduce
from typing import Any
from uuid import UUID

from django.db import connection
from django.db.models import Q, QuerySet

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.user import User

from products.actions.backend.facade.enums import ACTIONS_ARRAY_JSONPATH
from products.cdp.backend.flag_gated_templates import FLAG_GATED_TEMPLATE_IDS, gated_template_enabled
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions import HogFunction

_B = "products.cdp.backend."

_LAZY = {"HogFunctionSerializer": "api.hog_function"}

__all__ = [
    *sorted(_LAZY),
    "HogFunctionActionReference",
    "count_hog_functions_referencing_actions",
    "create_hog_functions",
    "has_enabled_hog_function_for_warehouse_table",
    "hog_functions_referencing_action",
    "is_hog_function_template_available",
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


@frozen
class HogFunctionActionReference:
    """A live hog function whose filters match on an action."""

    id: UUID
    name: str | None
    created_at: datetime
    created_by_id: int | None


def hog_functions_referencing_action(*, team_id: int, action_id: int, limit: int) -> list[HogFunctionActionReference]:
    """Up to `limit` live hog functions of the team whose filters match on the action."""
    vars_json = json.dumps({"id": action_id, "id_str": str(action_id)})
    rows = (
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
        HogFunction.objects.filter(team_id=team_id, deleted=False)
        .extra(
            where=[f"jsonb_path_exists(filters, '{ACTIONS_ARRAY_JSONPATH}', %s::jsonb)"],
            params=[vars_json],
        )
        .values("id", "name", "created_at", "created_by_id")
    )
    return [HogFunctionActionReference(**row) for row in rows[:limit]]


def count_hog_functions_referencing_actions(*, team_id: int, action_ids: Sequence[int]) -> dict[int, int]:
    """For each action, how many live hog functions of the team match on it. An action without one is absent."""
    if not action_ids:
        return {}
    hog_function_table = HogFunction._meta.db_table
    # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (parameterized via %s)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT aid, count(*) FROM unnest(%s::int[]) AS aid
            CROSS JOIN LATERAL (
                SELECT 1 FROM {hog_function_table}
                WHERE team_id = %s AND NOT deleted
                AND jsonb_path_exists(filters, '{ACTIONS_ARRAY_JSONPATH}', jsonb_build_object('id', aid, 'id_str', aid::text))
            ) AS matched
            GROUP BY aid
            """,
            [list(action_ids), team_id],
        )
        return dict(cursor.fetchall())


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)
