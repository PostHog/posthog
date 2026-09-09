from typing import Literal

from django.db import connections

from opentelemetry import trace

from posthog.utils import get_safe_cache, safe_cache_set

DefinitionTable = Literal["posthog_eventdefinition", "posthog_propertydefinition"]
SearchPlan = Literal["project_scan", "trigram"]

# Above this many definitions, walking the project's rows costs more than the global trigram index.
# Measured on production: at ~140k rows the project scan still wins by 40x; at ~600k rows the two
# are level for short terms; the largest projects have millions of rows and must keep the index.
PROJECT_SCAN_MAX_DEFINITIONS = 50_000

# A project rarely crosses the threshold, and a stale answer only costs query time, never results.
SEARCH_PLAN_CACHE_SECONDS = 24 * 60 * 60


def seen_within_sql(column: str) -> str:
    """The `exclude_stale` predicate: seen within `%(stale_interval)s`, or never seen at all.

    `posthog_eventdefinition` indexes `(COALESCE(project_id, team_id), last_seen_at)`, so with the
    project filter this predicate is an index range and reads only the project's recent rows.
    """
    return f"({column} IS NULL OR {column} > NOW() - %(stale_interval)s::interval)"


def search_plan(
    table: DefinitionTable, project_id: int, db_alias: str, *, seen_within_days: int | None = None
) -> SearchPlan:
    """Picks how a `?search=` on a definitions table should reach the project's rows.

    Postgres cannot scope the trigram GIN index on `name` to one project, so for the common small
    project it reads posting lists for every project before intersecting. Small projects are
    faster to scan through their own unique index and filter in place; only the few huge projects
    are better off with the trigram index. The count is bounded so it stays cheap for those.

    A search that excludes stale definitions only ever walks the project's recent rows, so
    `seen_within_days` bounds the count by those. Most huge projects have few recent definitions
    and take the project scan too.
    """
    plan = _cached_search_plan(table, project_id, db_alias, seen_within_days)
    trace.get_current_span().set_attribute("taxonomy_search_plan", plan)
    return plan


def _cached_search_plan(
    table: DefinitionTable, project_id: int, db_alias: str, seen_within_days: int | None
) -> SearchPlan:
    cache_key = f"taxonomy_search_plan:{table}:{project_id}:{seen_within_days}"
    # A cache outage must only cost the count query, never the search itself.
    cached = get_safe_cache(cache_key)
    if cached is not None:
        return cached

    conditions = "COALESCE(project_id, team_id) = %(project_id)s"
    params: dict[str, object] = {"project_id": project_id, "limit": PROJECT_SCAN_MAX_DEFINITIONS + 1}
    if seen_within_days is not None:
        conditions += f" AND {seen_within_sql('last_seen_at')}"
        params["stale_interval"] = f"{seen_within_days} days"

    with connections[db_alias].cursor() as cursor:
        cursor.execute(
            f"SELECT count(*) FROM (SELECT 1 FROM {table} WHERE {conditions} LIMIT %(limit)s) bounded", params
        )
        definition_count = cursor.fetchone()[0]

    plan: SearchPlan = "trigram" if definition_count > PROJECT_SCAN_MAX_DEFINITIONS else "project_scan"
    safe_cache_set(cache_key, plan, SEARCH_PLAN_CACHE_SECONDS)
    return plan
