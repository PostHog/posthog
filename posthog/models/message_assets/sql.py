from django.conf import settings

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_MESSAGE_ASSETS, kafka_engine
from posthog.kafka_client.topics import KAFKA_MESSAGE_ASSETS

# AUX-resident table family modelled on `hog_invocation_results`. One row per
# successfully sent email, keyed by (invocation_id, action_id) — a single
# workflow invocation can fan out to multiple email steps. Rendered HTML lives
# inline in the `html` column; columnar storage means listing queries don't read it.
MESSAGE_ASSETS_TABLE = "message_assets"
MESSAGE_ASSETS_DATA_TABLE = f"{MESSAGE_ASSETS_TABLE}_data"


# Writes go to the local data table — the distributed read alias isn't writable.
INSERT_MESSAGE_ASSET_SQL = f"""
INSERT INTO {MESSAGE_ASSETS_DATA_TABLE} (
    team_id,
    function_kind,
    function_id,
    parent_run_id,
    invocation_id,
    action_id,
    kind,
    distinct_id,
    person_id,
    recipient,
    subject,
    status,
    sent_at,
    version,
    is_deleted,
    html,
    _timestamp,
    _offset,
    _partition
)
SELECT
    %(team_id)s,
    %(function_kind)s,
    %(function_id)s,
    %(parent_run_id)s,
    %(invocation_id)s,
    %(action_id)s,
    %(kind)s,
    %(distinct_id)s,
    %(person_id)s,
    %(recipient)s,
    %(subject)s,
    %(status)s,
    %(sent_at)s,
    %(version)s,
    %(is_deleted)s,
    %(html)s,
    now(),
    0,
    0
"""

KAFKA_MESSAGE_ASSETS_TABLE = f"kafka_{MESSAGE_ASSETS_TABLE}"

# `html` is last because it dominates row size; column-oriented reads mean
# listing queries never touch it.
MESSAGE_ASSETS_KAFKA_COLUMNS = """
    team_id Int64,
    function_kind LowCardinality(String),
    function_id String,
    parent_run_id String,
    invocation_id String,
    action_id String,
    kind LowCardinality(String),
    distinct_id String,
    person_id String,
    recipient String,
    subject String,
    status LowCardinality(String),
    sent_at DateTime64(6, 'UTC'),
    version UInt64,
    is_deleted UInt8,
    html String
""".strip()

# Backed by the warpstream-cyclotron named collection — same cluster the CDP
# producer writes to and the same one hog_invocation_results consumes from.
KAFKA_MESSAGE_ASSETS_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {KAFKA_MESSAGE_ASSETS_TABLE}
(
    {MESSAGE_ASSETS_KAFKA_COLUMNS}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_MESSAGE_ASSETS,
            group=CONSUMER_GROUP_MESSAGE_ASSETS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_CYCLOTRON_NAMED_COLLECTION,
        )
    }
SETTINGS kafka_skip_broken_messages = 100
"""
)
