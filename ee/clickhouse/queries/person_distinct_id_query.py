from datetime import timedelta

from ee.clickhouse.materialized_columns.util import cache_for
from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS, GET_TEAM_PERSON_DISTINCT_IDS_NEW_TABLE
from posthog.models.async_migration import is_async_migration_complete, is_async_migration_required
from posthog.settings import BENCHMARK, TEST

using_new_table = TEST or BENCHMARK
migration_name = "0003_fill_person_distinct_id2"


def get_team_distinct_ids_query(team_id: int) -> str:
    from ee.clickhouse.client import substitute_params

    global using_new_table

    using_new_table = using_new_table or _fetch_person_distinct_id2_ready()

    if using_new_table:
        return substitute_params(GET_TEAM_PERSON_DISTINCT_IDS_NEW_TABLE, {"team_id": team_id})
    else:
        return substitute_params(GET_TEAM_PERSON_DISTINCT_IDS, {"team_id": team_id})


is_ready = False

# :TRICKY: Avoid overly eagerly checking whether the migration is complete.
# We instead cache negative responses for a minute and a positive one forever.
def _fetch_person_distinct_id2_ready() -> bool:
    global is_ready

    if is_ready:
        return True
    is_ready = not _is_person_distinct_id2_migration_required_cached() or _fetch_person_distinct_id2_ready_cached()
    return is_ready


@cache_for(timedelta(years=99))
def _is_person_distinct_id2_migration_required_cached() -> bool:
    return is_async_migration_required(migration_name)


@cache_for(timedelta(minutes=1))
def _fetch_person_distinct_id2_ready_cached() -> bool:
    return is_async_migration_complete(migration_name)
