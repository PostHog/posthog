import uuid
from enum import Enum

from django.conf import settings


class ReplicationScheme(str, Enum):
    NOT_SHARDED = "NOT_SHARDED"
    SHARDED = "SHARDED"
    REPLICATED = "REPLICATED"


# Relevant documentation:
# - https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/
# - https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/replacingmergetree/
# - https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/replication/
class MergeTreeEngine:
    ENGINE = ""
    REPLICATED_ENGINE = ""

    def __init__(self, table: str, replication_scheme: ReplicationScheme = ReplicationScheme.REPLICATED, **kwargs):
        self.table = table
        self.replication_scheme = replication_scheme
        self.kwargs = kwargs

    def __str__(self):
        replication_scheme = self.replication_scheme

        if not settings.CLICKHOUSE_REPLICATION:
            replication_scheme = ReplicationScheme.NOT_SHARDED

        if replication_scheme == ReplicationScheme.NOT_SHARDED:
            return self.ENGINE.format(**self.kwargs)

        if replication_scheme == ReplicationScheme.SHARDED:
            shard_key, replica_key = "{shard}", "{replica}"
        else:
            shard_key, replica_key = "noshard", "{replica}-{shard}"

        if settings.TEST:
            shard_key = f"{str(uuid.uuid4())}_{shard_key}"

        zk_path = f"/clickhouse/tables/{shard_key}/posthog.{self.table}"
        return self.REPLICATED_ENGINE.format(zk_path=zk_path, replica_key=replica_key, **self.kwargs)


class ReplacingMergeTree(MergeTreeEngine):
    ENGINE = "ReplacingMergeTree({ver})"
    REPLICATED_ENGINE = "ReplicatedReplacingMergeTree('{zk_path}', '{replica_key}', {ver})"


class CollapsingMergeTree(MergeTreeEngine):
    ENGINE = "CollapsingMergeTree({ver})"
    REPLICATED_ENGINE = "ReplicatedCollapsingMergeTree('{zk_path}', '{replica_key}', {ver})"


class Distributed:
    def __init__(self, data_table: str, sharding_key: str):
        self.data_table = data_table
        self.sharding_key = sharding_key

    def __str__(self):
        return f"Distributed('{settings.CLICKHOUSE_CLUSTER}', '{settings.CLICKHOUSE_DATABASE}', '{self.data_table}', {self.sharding_key})"
