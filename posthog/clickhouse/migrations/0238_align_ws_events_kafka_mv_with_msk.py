from pathlib import Path

from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import (
    DROP_EVENTS_JSON_WS_MV_SQL,
    DROP_KAFKA_EVENTS_JSON_WS_TABLE_SQL,
    EVENTS_TABLE_JSON_WS_MV_SQL,
    KAFKA_EVENTS_TABLE_JSON_WS_SQL,
)

# Align the WarpStream events pipeline (kafka_events_json_ws + events_json_ws_mv)
# with the MSK events pipeline (kafka_events_json + events_json_mv) on
# NodeRole.INGESTION_EVENTS. The current WS MV is a passthrough — it never
# projects mat_* / $group_* / $window_id / $session_id from `properties`, so
# every row ingested via WS lands with NULL/empty values in those columns on
# `sharded_events`. We fix this by dropping the existing WS kafka + MV and
# re-creating them as a byte-for-byte clone of the region's MSK pipeline
# (with only the table name and `FROM` clause rewritten on the MV).
#
# In prod-us and prod-eu the MSK MV bodies have diverged substantially and
# carry region-specific materialized column lists. We therefore ship per-region
# baked DDL as sidecar .sql files (captured from prod `INGESTION_EVENTS`
# nodes) rather than attempting to regenerate them from Python templates. The
# DEV/CI fallback uses the code-defined templates for the same reason 0232
# used them.
_SQL_DIR = Path(__file__).parent / "sql" / "0238"

if settings.CLOUD_DEPLOYMENT == "US":
    _kafka_ddl = (_SQL_DIR / "us_kafka.sql").read_text()
    _mv_ddl = (_SQL_DIR / "us_mv.sql").read_text()
elif settings.CLOUD_DEPLOYMENT == "EU":
    _kafka_ddl = (_SQL_DIR / "eu_kafka.sql").read_text()
    _mv_ddl = (_SQL_DIR / "eu_mv.sql").read_text()
else:
    _kafka_ddl = KAFKA_EVENTS_TABLE_JSON_WS_SQL()
    _mv_ddl = EVENTS_TABLE_JSON_WS_MV_SQL()

operations = (
    []
    if settings.CLOUD_DEPLOYMENT not in ("US", "EU", "DEV")
    else [
        # Order matters: drop the MV first so it stops consuming from the
        # kafka engine, then drop the kafka engine, then recreate both.
        run_sql_with_exceptions(
            DROP_EVENTS_JSON_WS_MV_SQL,
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions(
            DROP_KAFKA_EVENTS_JSON_WS_TABLE_SQL,
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions(
            _kafka_ddl,
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions(
            _mv_ddl,
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
    ]
)
