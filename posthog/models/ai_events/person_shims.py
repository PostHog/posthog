from django.conf import settings

from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import Distributed
from posthog.models.person.sql import (
    PERSON_DISTINCT_ID2_TABLE,
    PERSON_DISTINCT_ID2_TABLE_BASE_SQL,
    PERSONS_TABLE,
    PERSONS_TABLE_BASE_SQL,
)

# Distributed shim tables on the ai_events satellite cluster that forward
# person joins back to the main cluster. Without these, HogQL queries against
# ai_events that touch person.* fail with UNKNOWN_TABLE because the real
# person tables only live on NodeRole.DATA.
#
# Column DDL is imported from posthog.models.person.sql so the shim stays
# structurally in sync with the source template. Any ALTER to the source
# table on the main cluster still needs to be mirrored here by a dedicated
# migration targeting NodeRole.AI_EVENTS — the import only covers CREATE
# shape, not the ALTER timeline.


def PERSON_DISTINCT_ID2_AI_EVENTS_SHIM_SQL() -> str:
    return PERSON_DISTINCT_ID2_TABLE_BASE_SQL.format(
        table_name=PERSON_DISTINCT_ID2_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=Distributed(data_table=PERSON_DISTINCT_ID2_TABLE, cluster=settings.CLICKHOUSE_CLUSTER),
        extra_fields="",
    )


def PERSON_AI_EVENTS_SHIM_SQL() -> str:
    return PERSONS_TABLE_BASE_SQL.format(
        table_name=PERSONS_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=Distributed(data_table=PERSONS_TABLE, cluster=settings.CLICKHOUSE_CLUSTER),
        extra_fields="",
    )
