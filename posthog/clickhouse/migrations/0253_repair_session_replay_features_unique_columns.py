from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_feature_sql import UNIQ_COMBINED_PRECISION

# Migration 0252 used a single ALTER statement that both dropped the old uniqExact
# unique_url_count + unique_click_target_count columns and ADDed them back as
# uniqCombined.
#
# This resulted in these two columns being dropped and not re-added.
#
# This migration re-adds them.

REPAIR_SQL = f"""
ALTER TABLE sharded_session_replay_features
    ADD COLUMN IF NOT EXISTS unique_url_count AggregateFunction(uniqCombined({UNIQ_COMBINED_PRECISION}), String),
    ADD COLUMN IF NOT EXISTS unique_click_target_count AggregateFunction(uniqCombined({UNIQ_COMBINED_PRECISION}), Int64)
"""

operations = [
    run_sql_with_exceptions(
        REPAIR_SQL,
        node_roles=[NodeRole.AUX],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
]
