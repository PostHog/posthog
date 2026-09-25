from typing import Literal

from django.db import connections

from opentelemetry import trace

from posthog.dataclasses import frozen
from posthog.utils import get_safe_cache, safe_cache_set

DefinitionTable = Literal["posthog_eventdefinition", "posthog_propertydefinition"]

# Above this many definitions, walking the project's rows costs more than the global trigram index.
# Measured on production: at ~140k rows the project scan still wins by 40x; at ~600k rows the two
# are level for short terms; the largest projects have millions of rows and must keep the index.
PROJECT_SCAN_MAX_DEFINITIONS = 50_000

# Nothing indexes `last_seen_at`, so a recency-ordered event list sorts every definition of the project
# for each page. Above this many definitions the list defaults to name order, which the unique index
# returns directly. Below it, the sort stays cheap enough to keep the recency default.
NAME_ORDER_MIN_DEFINITIONS = 100_000

# A project rarely crosses a threshold, so one count serves it for a day.
# A stale count costs query time for a project that has grown past a threshold.
# For a project that has fallen back below one, the stale count also holds the bounded count and the
# name order it selects, so the list reads as large until the key expires.
SEARCH_PLAN_CACHE_SECONDS = 24 * 60 * 60

# An exact count over a large project walks its whole index range on every page load. Its list
# endpoints stop counting here instead; small projects keep exact counts.
LARGE_PROJECT_COUNT_CAP = 10_000


@frozen
class ProjectDefinitionScale:
    """How a definition list reads one project's rows, decided from one cached bounded count."""

    large: bool
    orders_by_name: bool


def project_definition_scale(table: DefinitionTable, project_id: int, db_alias: str) -> ProjectDefinitionScale:
    definition_count = _cached_definition_count(table, project_id, db_alias)
    scale = ProjectDefinitionScale(
        large=definition_count > PROJECT_SCAN_MAX_DEFINITIONS,
        orders_by_name=definition_count > NAME_ORDER_MIN_DEFINITIONS,
    )
    # Every reader of the count records it, so a request tells which access path it took.
    span = trace.get_current_span()
    span.set_attribute("taxonomy_search_plan", "trigram" if scale.large else "project_scan")
    span.set_attribute("taxonomy_definition_count", definition_count)
    return scale


def is_large_project(table: DefinitionTable, project_id: int, db_alias: str) -> bool:
    """Whether the project holds more than PROJECT_SCAN_MAX_DEFINITIONS rows of `table` (cached for a day).

    The list endpoints use this to pick their search index, their sort statement and their count:
    Postgres cannot scope the trigram GIN index on `name` to one project, so a small project is faster
    to scan through its own scoped index, and a large project is too expensive to sort or count in full.
    """
    return project_definition_scale(table, project_id, db_alias).large


def bounded_count_sql(source_sql: str, order_by: str) -> str:
    """A count over `source_sql` (a FROM/WHERE fragment) that stops at %(count_cap)s rows.

    `order_by` is the key of the index that serves the scope filter in `source_sql` (`name` on both
    definition tables). Without it, Postgres may satisfy the LIMIT from a sequential scan of the whole
    table when it estimates the project's rows to be dense enough; ordering by the index key keeps the
    count on the project-scoped index. The order itself is irrelevant to the count.
    """
    return f"SELECT count(*) FROM (SELECT 1 {source_sql} ORDER BY {order_by} LIMIT %(count_cap)s) bounded"


def _cached_definition_count(table: DefinitionTable, project_id: int, db_alias: str) -> int:
    # The key is not `taxonomy_search_plan:*`, which holds a plan name, so a release that reads the count
    # never reads an entry an earlier release wrote, in either direction.
    cache_key = f"taxonomy_definition_count:{table}:{project_id}"
    # A cache outage must only cost the count query, never the search itself.
    cached = get_safe_cache(cache_key)
    if cached is not None:
        return cached

    limit = max(PROJECT_SCAN_MAX_DEFINITIONS, NAME_ORDER_MIN_DEFINITIONS) + 1
    with connections[db_alias].cursor() as cursor:
        # Ordering by the index key keeps the probe on the project-scoped index; see `bounded_count_sql`.
        cursor.execute(
            f"SELECT count(*) FROM (SELECT 1 FROM {table} WHERE COALESCE(project_id, team_id) = %(project_id)s ORDER BY name LIMIT %(limit)s) bounded",
            {"project_id": project_id, "limit": limit},
        )
        definition_count = cursor.fetchone()[0]

    safe_cache_set(cache_key, definition_count, SEARCH_PLAN_CACHE_SECONDS)
    return definition_count
