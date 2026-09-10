"""Inversion hooks that let data_modeling sync managed viewsets whose *contents* are owned by
other products (revenue_analytics, engineering_analytics) without importing them.

Both products already depend on data_modeling, so a direct import from here would create a
dependency cycle. Instead each product registers its view provider at app-ready time (see its
AppConfig.ready()), and DataWarehouseManagedViewSet.sync_views() calls through the registered
callable, keyed by viewset kind. When nothing is registered for a kind, the caller raises
UnsupportedViewsetKind, which keeps data_modeling importable on its own.

Scoped to view provision: DataWarehouseManagedViewSet.to_saved_query_metadata still imports
revenue_analytics' schemas directly to derive its per-view metadata. That is a separate coupling
on the query-resolution path, not this one.

Kept LIGHT on purpose: this module is imported on the django.setup() path from AppConfig.ready(),
so it must never import Django models or heavy product internals at module scope.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.hogql.database.models import FieldOrTable

    from posthog.models.team import Team


@dataclasses.dataclass(frozen=True)
class ProvidedView:
    """One view a product wants data_modeling to manage. ``query`` is the raw HogQL SELECT body —
    data_modeling wraps it into ``{"kind": "HogQLQuery", "query": ...}`` itself. ``fields`` are HogQL
    fields — data_modeling converts them to stored ``columns`` metadata itself.
    """

    name: str
    query: str
    fields: dict[str, FieldOrTable]
    # Materialized views get a 12h sync schedule and a managed DAG node. A non-materialized view
    # (e.g. engineering analytics) is computed at query time — no schedule, no DAG, no S3 table.
    materialized: bool = True


ExpectedViewsProvider = Callable[["Team"], list[ProvidedView]]
_expected_views_providers: dict[str, ExpectedViewsProvider] = {}


def register_expected_views_provider(kind: str, fn: ExpectedViewsProvider) -> None:
    _expected_views_providers[kind] = fn


def get_expected_views_provider(kind: str) -> ExpectedViewsProvider | None:
    return _expected_views_providers.get(kind)
