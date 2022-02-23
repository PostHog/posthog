from enum import Enum

from django.conf import settings


class ReplicationScheme(str, Enum):
    NOT_SHARDED = "NOT_SHARDED"
    SHARDED = "SHARDED"
    REPLICATED = "REPLICATED"


# Note: This does not list every table engine, just ones used in our codebase
class TableEngine(str, Enum):
    ReplacingMergeTree = "ReplacingMergeTree"
    CollapsingMergeTree = "CollapsingMergeTree"


class TableEngine:
    def __str__(self):
        return self.format()


# Relevant documentation:
# - https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/
# - https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/replacingmergetree/
# - https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/replication/
class MergeTreeEngine(TableEngine):
    def __init__(self, table: str, replication_scheme: ReplicationScheme = ReplicationScheme.REPLICATED, **kwargs):
        self.table = table
        self.replication_scheme = replication_scheme
        self.kwargs = kwargs

    def format(self):
        replication_scheme = self.replication_scheme

        if not settings.CLICKHOUSE_REPLICATION:
            replication_scheme = ReplicationScheme.NOT_SHARDED

        if replication_scheme == ReplicationScheme.NOT_SHARDED:
            return self.ENGINE.format(**self.kwargs)

        if replication_scheme == ReplicationScheme.SHARDED:
            shard_key, replica_key = "{shard}", "{replica}"
        else:
            shard_key, replica_key = "noshard", "{replica}-{shard}"

        zk_path = f"/clickhouse/tables/{shard_key}/posthog.{self.table}"
        return self.REPLICATED_ENGINE.format(zk_path=zk_path, replica_key=replica_key, **self.kwargs)


class ReplacingMergeTree(MergeTreeEngine):
    ENGINE = "ReplacingMergeTree({ver})"
    REPLICATED_ENGINE = "ReplicatedReplacingMergeTree('{zk_path}', '{replica_key}', {ver})"


class CollapsingMergeTree(MergeTreeEngine):
    ENGINE = "CollapsingMergeTree({ver})"
    REPLICATED_ENGINE = "ReplicatedCollapsingMergeTree('{zk_path}', '{replica_key}', {ver})"
