from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Drop the locally-created WarpStream Kafka engine tables and their materialized
# views for the three topics where 0227 created them without a cloud-only guard:
# `log_entries`, `app_metrics2`, and `tophog`.
#
# Why drop the WS side rather than the MSK side, given that cloud is fully on WS
# now: in non-cloud environments (local dev, CI, hobby) all of the OTHER topics
# in this family are MSK-only — every `_ws` create migration after 0227 (0232
# onward) carries a cloud-only guard, so their WS pairs were never created
# locally and the cleanup migration 0248 was correspondingly cloud-only. Local
# has settled on MSK as its single-consumer convention for the whole set.
# 0227 is the one outlier that landed before the guard pattern was established,
# so locally there are TWO consumer groups for these three topics — same
# broker, same topic — and `ReplicatedAggregatingMergeTree` doubles every
# metric count after the duplicate inserts.
#
# Dropping the WS side restores local uniformity (every consumer-having topic
# reads via MSK locally). Dropping the MSK side would have worked functionally
# but would leave local with three topics on WS and the other ~16 on MSK,
# which is harder to reason about during development of services that touch
# multiple of these tables. Cloud is unaffected because cloud already dropped
# the MSK side for these three (and many others) via 0248 — cloud reads via WS
# everywhere. Local will follow cloud onto WS for the whole set if/when the
# cloud-only guards on the 0232+ create migrations are eventually retired and
# the WS pairs get created locally; until then, MSK-everywhere is the local
# baseline this migration is restoring for the three outlier topics.
#
# Inverted polarity guard: skip on cloud (cloud's WS-side tables are the live
# consumers and must stay), run on non-cloud. Order: drop the MV first so it
# stops feeding the writable target, then drop the Kafka engine table.
# `IF EXISTS` keeps the migration idempotent.
#
# All operations target `NodeRole.DATA`. That's the actual role of the single
# local ClickHouse node (`hostClusterRole=data` in docker/clickhouse/config.d/
# default.xml), so the drops land on the host where the `_ws` tables actually
# live. The original 0227 creates targeted `INGESTION_SMALL` / `INGESTION_MEDIUM`,
# but those roles don't exist on any local host config — the WS tables landed
# on the DATA node anyway because `migration_tools.py:75-80` collapses node_roles
# to `NodeRole.ALL` in non-cloud / debug / E2E (and non-MULTINODE_CLICKHOUSE),
# fanning the query to the single host regardless of the requested role.

operations = (
    []
    if settings.CLOUD_DEPLOYMENT in ("US", "EU", "DEV")
    else [
        # log_entries
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS log_entries_ws_mv",
            node_roles=[NodeRole.DATA],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_log_entries_ws",
            node_roles=[NodeRole.DATA],
        ),
        # app_metrics2
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS app_metrics2_ws_mv",
            node_roles=[NodeRole.DATA],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_app_metrics2_ws",
            node_roles=[NodeRole.DATA],
        ),
        # tophog
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS tophog_ws_mv",
            node_roles=[NodeRole.DATA],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_tophog_ws",
            node_roles=[NodeRole.DATA],
        ),
    ]
)
