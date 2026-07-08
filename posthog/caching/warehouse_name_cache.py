"""Request/task-scoped memoization of the warehouse names a team's queries can reference.

Import-light on purpose: wired from `PostHogConfig.ready()` so the invalidation receivers connect
at django.setup() in every process, so it must not drag `posthog.schema` / `posthog.hogql_queries`
onto the setup path. The sole consumer is the HogQL cache fingerprint
(`posthog.hogql_queries.access_controlled_resources`).
"""

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from typing import NamedTuple

from django.core.signals import request_finished, request_started
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from celery.signals import task_postrun, task_prerun
from opentelemetry import trace

tracer = trace.get_tracer(__name__)


class WarehouseNames(NamedTuple):
    table_names: frozenset[str]
    view_names: frozenset[str]


# Scoped memoization for `get_warehouse_names_for_team`. A dashboard load constructs one query
# runner per insight tile, and each runner's cache fingerprint (`queried_access_controlled_resources`)
# would otherwise rescan every warehouse table and saved query of the team — on warehouse-heavy
# teams that scan dominates the cost of serializing HogQL tiles. We cache the name sets keyed by
# team_id for the lifetime of an explicitly-opened scope and discard the cache when the scope closes.
#
# The ContextVar defaults to ``None`` which means "no scope active — do not cache". This is
# critical: a thread-lifetime cache on a Celery worker could partition cache keys against a stale
# view of the team's warehouse objects long after they changed. Scopes are opened at HTTP request
# boundaries (`request_started` / `request_finished`) and Celery task boundaries (`task_prerun` /
# `task_postrun`); callers running outside those boundaries simply pay the query cost rather than
# risk stale data.
_warehouse_names_cache_var: ContextVar[dict[int, WarehouseNames] | None] = ContextVar(
    "warehouse_names_cache", default=None
)


@contextlib.contextmanager
def warehouse_names_cache_scope() -> Iterator[None]:
    """Open a memoization scope for ``get_warehouse_names_for_team``.

    Use this to bracket any non-HTTP, non-Celery code path that fingerprints many queries for the
    same team (e.g. management commands or tests that want the per-request behavior without going
    through the signal plumbing).
    """
    token = _warehouse_names_cache_var.set({})
    try:
        yield
    finally:
        _warehouse_names_cache_var.reset(token)


@receiver(request_started)
@receiver(task_prerun)
def _open_warehouse_names_cache_scope(**_kwargs: object) -> None:
    _warehouse_names_cache_var.set({})


@receiver(request_finished)
@receiver(task_postrun)
def _close_warehouse_names_cache_scope(**_kwargs: object) -> None:
    _warehouse_names_cache_var.set(None)


@receiver(post_save, sender="warehouse_sources.DataWarehouseTable")
@receiver(post_delete, sender="warehouse_sources.DataWarehouseTable")
@receiver(post_save, sender="warehouse_sources.ExternalDataSource")
@receiver(post_delete, sender="warehouse_sources.ExternalDataSource")
@receiver(post_save, sender="data_modeling.DataWarehouseSavedQuery")
@receiver(post_delete, sender="data_modeling.DataWarehouseSavedQuery")
def _invalidate_warehouse_names_cache_on_change(**_kwargs: object) -> None:
    # ExternalDataSource is a sender too: the prefixed table names depend on the source's
    # prefix/source_type/access_method, not just the table rows.
    cache = _warehouse_names_cache_var.get()
    if cache is not None:
        cache.clear()


def get_warehouse_names_for_team(team_id: int) -> WarehouseNames:
    """Every name a team's warehouse tables and views are queryable under.

    External tables are queryable under BOTH their raw name and the prefixed
    source_type.prefix.table key (see the database.py schema build), so both forms are collected —
    otherwise a denied user could read an allowed user's cached rows via the raw name.

    Memoized per request/task scope — see ``_warehouse_names_cache_var``.
    """
    cache = _warehouse_names_cache_var.get()
    if cache is not None and team_id in cache:
        return cache[team_id]

    # Deferred: keeps the hogql layer and the product models off this module's import path, which
    # PostHogConfig.ready() loads at django.setup().
    from posthog.hogql.database.database import get_data_warehouse_table_name_from_parts  # noqa: PLC0415

    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery  # noqa: PLC0415
    from products.warehouse_sources.backend.facade.models import DataWarehouseTable  # noqa: PLC0415

    with tracer.start_as_current_span("get_warehouse_names_for_team") as span:
        span.set_attribute("team_id", team_id)

        # values_list via the raw manager keeps this to one slim JOINed SELECT: materializing full
        # models would pull the fat `columns` JSON of every table plus the default manager's
        # select_related/prefetch_related eager loads.
        table_names: set[str] = set()
        for name, source_id, source_type, prefix, access_method in (
            DataWarehouseTable.raw_objects.filter(team_id=team_id)
            .exclude(deleted=True)
            .values_list(
                "name",
                "external_data_source_id",
                "external_data_source__source_type",
                "external_data_source__prefix",
                "external_data_source__access_method",
            )
        ):
            table_names.add(name)
            table_names.add(
                get_data_warehouse_table_name_from_parts(
                    name,
                    source_id=source_id,
                    source_type=source_type,
                    prefix=prefix,
                    access_method=access_method,
                )
            )

        view_names = frozenset(
            DataWarehouseSavedQuery.objects.filter(team_id=team_id).exclude(deleted=True).values_list("name", flat=True)
        )

    names = WarehouseNames(table_names=frozenset(table_names), view_names=view_names)
    if cache is not None:
        cache[team_id] = names
    return names
