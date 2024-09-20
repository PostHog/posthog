import uuid
from enum import StrEnum
from typing import Optional

from django.conf import settings


class ReplicationScheme(StrEnum):
    NOT_SHARDED = "NOT_SHARDED"
    SHARDED = "SHARDED"
    REPLICATED = "REPLICATED"


# Relevant documentation:
# - https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/
# - https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/replacingmergetree/
# - https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/replication/
class MergeTreeEngine:
    ENGINE = "MergeTree()"
    REPLICATED_ENGINE = "ReplicatedMergeTree('{zk_path}', '{replica_key}')"

    def __init__(
        self,
        table: str,
        replication_scheme: ReplicationScheme = ReplicationScheme.REPLICATED,
        force_unique_zk_path=False,
        **kwargs,
    ):
        self.table = table
        self.replication_scheme = replication_scheme
        self.force_unique_zk_path = force_unique_zk_path
        self.kwargs = kwargs

        self.zookeeper_path_key: Optional[str] = None

    def set_zookeeper_path_key(self, zookeeper_path_key: str):
        "Used in situations where a unique zookeeper path is needed"
        self.zookeeper_path_key = zookeeper_path_key

    def __str__(self):
        replication_scheme = self.replication_scheme

        if replication_scheme == ReplicationScheme.NOT_SHARDED:
            return self.ENGINE.format(**self.kwargs)

        if replication_scheme == ReplicationScheme.SHARDED:
            shard_key, replica_key = "{shard}", "{replica}"
        else:
            shard_key, replica_key = "noshard", "{replica}-{shard}"

        # ZK is not automatically cleaned up after DROP TABLE. Avoid zk path conflicts in tests by generating unique paths.
        if (settings.TEST or settings.E2E_TESTING) and self.zookeeper_path_key is None or self.force_unique_zk_path:
            self.set_zookeeper_path_key(str(uuid.uuid4()))

        if self.zookeeper_path_key is not None:
            shard_key = f"{self.zookeeper_path_key}_{shard_key}"

        zk_path = f"/clickhouse/tables/{shard_key}/posthog.{self.table}"
        return self.REPLICATED_ENGINE.format(zk_path=zk_path, replica_key=replica_key, **self.kwargs)


class ReplacingMergeTree(MergeTreeEngine):
    ENGINE = "ReplacingMergeTree({ver})"
    REPLICATED_ENGINE = "ReplicatedReplacingMergeTree('{zk_path}', '{replica_key}', {ver})"


class CollapsingMergeTree(MergeTreeEngine):
    ENGINE = "CollapsingMergeTree({ver})"
    REPLICATED_ENGINE = "ReplicatedCollapsingMergeTree('{zk_path}', '{replica_key}', {ver})"


class AggregatingMergeTree(MergeTreeEngine):
    ENGINE = "AggregatingMergeTree()"
    REPLICATED_ENGINE = "ReplicatedAggregatingMergeTree('{zk_path}', '{replica_key}')"


class Distributed:
    def __init__(self, data_table: str, sharding_key: str):
        self.data_table = data_table
        self.sharding_key = sharding_key

    def __str__(self):
        return f"Distributed('{settings.CLICKHOUSE_CLUSTER}', '{settings.CLICKHOUSE_DATABASE}', '{self.data_table}', {self.sharding_key})"
