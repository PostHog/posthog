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

# Materialized columns added to the main cluster's `person` table via
# `ee.clickhouse.materialized_columns.columns.materialize()` are not part of
# PERSONS_TABLE_BASE_SQL — they are created at runtime. The HogQL printer
# rewrites `person.properties.<prop>` to `<table>.pmat_<prop>` whenever the
# materialized column is registered, so the Distributed shim must declare
# the same column name (with the underlying String type — the Distributed
# engine does not compute values, it just routes the column reference).
#
# When a new materialized column is added to the `person` table on the
# main cluster, add it here AND add a migration targeting NodeRole.AI_EVENTS
# that ALTERs the existing shim. Both are needed: this list keeps fresh
# environments (local dev, hobby, tests) in sync at table creation, while
# the ALTER updates production envs where the shim already exists.
PERSON_AI_EVENTS_SHIM_MATERIALIZED_COLUMNS: tuple[tuple[str, str], ...] = (("pmat_email", "String"),)


def PERSON_DISTINCT_ID2_AI_EVENTS_SHIM_SQL() -> str:
    return PERSON_DISTINCT_ID2_TABLE_BASE_SQL.format(
        table_name=PERSON_DISTINCT_ID2_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=Distributed(data_table=PERSON_DISTINCT_ID2_TABLE, cluster=settings.CLICKHOUSE_CLUSTER),
        extra_fields="",
    )


def PERSON_AI_EVENTS_SHIM_SQL() -> str:
    materialized_fields = "".join(
        f", {name} {column_type}" for name, column_type in PERSON_AI_EVENTS_SHIM_MATERIALIZED_COLUMNS
    )
    return PERSONS_TABLE_BASE_SQL.format(
        table_name=PERSONS_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=Distributed(data_table=PERSONS_TABLE, cluster=settings.CLICKHOUSE_CLUSTER),
        extra_fields=materialized_fields,
    )
