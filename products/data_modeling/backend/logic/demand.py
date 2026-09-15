from collections import defaultdict
from collections.abc import Collection
from datetime import UTC, datetime
from itertools import batched
from typing import TYPE_CHECKING

from django.db.models import Case, DateTimeField, F, Value, When
from django.db.models.functions import Greatest
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.redis import get_client

from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)

MODEL_DEMAND_FLAG = "data-modeling-track-model-demand"
SHARD_COUNT = 16
FLUSH_BATCH_SIZE = 1000

# A query arriving during the database write must survive acknowledgement of the older timestamp.
ACKNOWLEDGE = """
for i = 1, #ARGV, 2 do
    local score = redis.call('ZSCORE', KEYS[1], ARGV[i])
    if score and tonumber(score) <= tonumber(ARGV[i + 1]) then
        redis.call('ZREM', KEYS[1], ARGV[i])
    end
end
return 1
"""


class ModelDemand:
    @staticmethod
    def buffer_key(shard: int) -> str:
        return f"data_modeling:demand:{shard}"

    @staticmethod
    def enabled(team: "Team") -> bool:
        # This runs on the query hot path, so the flag is evaluated from the local definition cache only:
        # an inconclusive answer means "off", never an HTTP call and never a recorded demand.
        try:
            return bool(
                posthoganalytics.feature_enabled(
                    MODEL_DEMAND_FLAG,
                    str(team.uuid),
                    groups={"organization": str(team.organization_id), "project": str(team.pk)},
                    group_properties={
                        "organization": {"id": str(team.organization_id)},
                        "project": {"id": str(team.pk)},
                    },
                    only_evaluate_locally=True,
                    send_feature_flag_events=False,
                )
            )
        except Exception:
            return False

    @classmethod
    def record(cls, team_id: int, saved_query_ids: Collection[str]) -> None:
        if not saved_query_ids:
            return
        try:
            timestamp = timezone.now().timestamp()
            get_client().zadd(
                cls.buffer_key(team_id % SHARD_COUNT),
                {f"{team_id}:{saved_query_id}": timestamp for saved_query_id in saved_query_ids},
                gt=True,
            )
        except Exception:
            logger.exception("Failed to buffer model demand", team_id=team_id)

    @staticmethod
    def persist_team(team_id: int, demand: dict[str, float]) -> None:
        nodes_by_query: dict[str, set[str]] = defaultdict(set)
        query_by_node: dict[str, str] = {}
        for node in Node.objects.filter(team_id=team_id).values("id", "saved_query_id", "properties"):
            node_id = str(node["id"])
            query_id = node["saved_query_id"]
            properties = node["properties"] or {}
            if properties.get("origin") == "cross_dag_view":
                query_id = properties.get("saved_query_id")
            if query_id:
                nodes_by_query[str(query_id)].add(node_id)
                query_by_node[node_id] = str(query_id)

        upstream: dict[str, set[str]] = defaultdict(set)
        for source, target in Edge.objects.filter(team_id=team_id).values_list("source_id", "target_id"):
            upstream[str(target)].add(str(source))

        timestamps: dict[str, datetime] = {}
        # Visit newest demand first so shared ancestors only need one traversal.
        for query_id, timestamp in sorted(demand.items(), key=lambda item: item[1], reverse=True):
            pending = list(nodes_by_query.get(query_id, ()))
            while pending:
                node_id = pending.pop()
                if node_id in timestamps:
                    continue
                timestamps[node_id] = datetime.fromtimestamp(timestamp, UTC)
                pending.extend(upstream.get(node_id, ()))
                if equivalent_query := query_by_node.get(node_id):
                    pending.extend(nodes_by_query[equivalent_query])

        for batch in batched(timestamps, 500, strict=False):
            Node.objects.filter(team_id=team_id, id__in=batch).update(
                last_demand_at=Greatest(
                    F("last_demand_at"),
                    Case(
                        *(When(id=node_id, then=Value(timestamps[node_id])) for node_id in batch),
                        output_field=DateTimeField(),
                    ),
                )
            )

    @classmethod
    def flush(cls) -> None:
        client = get_client()
        failure: Exception | None = None
        failed_teams: set[int] = set()
        for shard in range(SHARD_COUNT):
            key = cls.buffer_key(shard)
            retained = 0
            while True:
                entries = client.zrange(key, retained, retained + FLUSH_BATCH_SIZE - 1, withscores=True)
                demand_by_team: dict[int, dict[str, float]] = defaultdict(dict)
                acknowledgements_by_team: dict[int, list[bytes | float]] = defaultdict(list)
                for member, timestamp in entries:
                    team_id, query_id = member.decode().split(":", 1)
                    demand_by_team[int(team_id)][query_id] = timestamp
                    acknowledgements_by_team[int(team_id)] += [member, timestamp]
                for team_id, demand in demand_by_team.items():
                    if team_id in failed_teams:
                        retained += len(demand)
                        continue
                    # A team that keeps failing must not withhold the later teams of this shard or any
                    # later shard, so each team is acknowledged on its own and the first error is
                    # re-raised once every shard is read.
                    try:
                        cls.persist_team(team_id, demand)
                        client.eval(ACKNOWLEDGE, 1, key, *acknowledgements_by_team[team_id])
                    except Exception as error:
                        logger.exception("Failed to flush model demand", team_id=team_id)
                        failure = failure or error
                        failed_teams.add(team_id)
                        retained += len(demand)
                if len(entries) < FLUSH_BATCH_SIZE:
                    break
        if failure is not None:
            raise failure
