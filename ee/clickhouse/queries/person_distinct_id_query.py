from datetime import timedelta

from ee.clickhouse.materialized_columns.util import cache_for
from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS, GET_TEAM_PERSON_DISTINCT_IDS_NEW_TABLE
from posthog.models.async_migration import is_async_migration_complete
from posthog.settings import BENCHMARK, TEST

using_new_table = TEST or BENCHMARK


def get_team_distinct_ids_query(team_id: int) -> str:
    from ee.clickhouse.client import substitute_params

    global using_new_table

    using_new_table = using_new_table or _fetch_person_distinct_id2_ready()

    if using_new_table:
        return substitute_params(GET_TEAM_PERSON_DISTINCT_IDS_NEW_TABLE, {"team_id": team_id})
    else:
        return substitute_params(GET_TEAM_PERSON_DISTINCT_IDS, {"team_id": team_id})


# :TRICKY: Avoid overly eagerly checking whether the migration is complete.
@cache_for(timedelta(minutes=15))
def _fetch_person_distinct_id2_ready() -> bool:
    return is_async_migration_complete("0003_fill_person_distinct_id2")
