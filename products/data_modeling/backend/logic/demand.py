"""Record when a model's output was last read, so that idle models can be told apart from used ones.

Demand arrives as (saved query id, last read time) pairs aggregated from the ClickHouse query log.
Reading a model also reads everything upstream of it, so a stamp propagates to every ancestor node.
"""

from collections import defaultdict
from datetime import datetime

from django.db.models import Q

from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node


def record_saved_query_demand(team_id: int, last_read_at: dict[str, datetime]) -> int:
    """Move `last_demand_at` forward on the nodes of the given saved queries and on all of their ancestors.

    A stamp never moves backwards, so replaying an older window is safe. Returns the number of nodes reached.
    """
    if not last_read_at:
        return 0

    nodes_by_query: dict[str, list[str]] = defaultdict(list)
    query_by_node: dict[str, str] = {}
    for node_id, saved_query_id in Node.objects.filter(team_id=team_id, saved_query__isnull=False).values_list(
        "id", "saved_query_id"
    ):
        nodes_by_query[str(saved_query_id)].append(str(node_id))
        query_by_node[str(node_id)] = str(saved_query_id)

    upstream: dict[str, list[str]] = defaultdict(list)
    for source_id, target_id in Edge.objects.filter(team_id=team_id).values_list("source_id", "target_id"):
        upstream[str(target_id)].append(str(source_id))

    demand_by_node: dict[str, datetime] = {}
    for saved_query_id, read_at in last_read_at.items():
        stack = list(nodes_by_query.get(saved_query_id, ()))
        while stack:
            node_id = stack.pop()
            seen = demand_by_node.get(node_id)
            if seen is not None and seen >= read_at:
                continue
            demand_by_node[node_id] = read_at
            stack.extend(upstream[node_id])
            # A saved query with nodes in several DAGs has its lineage recorded on each of them.
            if (query_id := query_by_node.get(node_id)) is not None:
                stack.extend(sibling for sibling in nodes_by_query[query_id] if sibling != node_id)

    nodes_by_stamp: dict[datetime, list[str]] = defaultdict(list)
    for node_id, read_at in demand_by_node.items():
        nodes_by_stamp[read_at].append(node_id)
    for read_at, node_ids in nodes_by_stamp.items():
        Node.objects.filter(team_id=team_id, id__in=node_ids).filter(
            Q(last_demand_at__isnull=True) | Q(last_demand_at__lt=read_at)
        ).update(last_demand_at=read_at)

    return len(demand_by_node)
