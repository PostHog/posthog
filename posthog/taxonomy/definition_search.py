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


def search_plan(table: DefinitionTable, project_id: int, db_alias: str) -> SearchPlan:
    """Picks how a `?search=` on a definitions table should reach the project's rows.

    Postgres cannot scope the trigram GIN index on `name` to one project, so for the common small
    project it reads posting lists for every project before intersecting. Small projects are
    faster to scan through their own unique index and filter in place; only the few huge projects
    are better off with the trigram index. The count is bounded so it stays cheap for those.
    """
    plan = _cached_search_plan(table, project_id, db_alias)
    trace.get_current_span().set_attribute("taxonomy_search_plan", plan)
    return plan


def _cached_search_plan(table: DefinitionTable, project_id: int, db_alias: str) -> SearchPlan:
    cache_key = f"taxonomy_search_plan:{table}:{project_id}"
    # A cache outage must only cost the count query, never the search itself.
    cached = get_safe_cache(cache_key)
    if cached is not None:
        return cached

    with connections[db_alias].cursor() as cursor:
        cursor.execute(
            f"SELECT count(*) FROM (SELECT 1 FROM {table} WHERE COALESCE(project_id, team_id) = %(project_id)s LIMIT %(limit)s) bounded",
            {"project_id": project_id, "limit": PROJECT_SCAN_MAX_DEFINITIONS + 1},
        )
        definition_count = cursor.fetchone()[0]

    plan: SearchPlan = "trigram" if definition_count > PROJECT_SCAN_MAX_DEFINITIONS else "project_scan"
    safe_cache_set(cache_key, plan, SEARCH_PLAN_CACHE_SECONDS)
    return plan
