"""Record when a model's output was last read, so that idle models can be told apart from used ones.

Demand arrives as (saved query id, last read time) pairs aggregated from the ClickHouse query log.
Reading a model also reads everything upstream of it, so a stamp propagates to every ancestor node.
"""

from collections import defaultdict
from datetime import datetime
from itertools import batched

from django.db.models import Case, DateTimeField, F, Value, When
from django.db.models.functions import Greatest

from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node

UPDATE_BATCH_SIZE = 500


def record_saved_query_demand(team_id: int, last_read_at: dict[str, datetime]) -> int:
    """Move `last_demand_at` forward on the nodes of the given saved queries and on all of their ancestors.

    A stamp never moves backwards, so replaying an older window is safe. Returns the number of nodes reached.
    """
    if not last_read_at:
        return 0

    nodes_by_query: dict[str, list[str]] = defaultdict(list)
    query_by_node: dict[str, str] = {}
    for node in Node.objects.filter(team_id=team_id).values("id", "saved_query_id", "properties"):
        properties = node["properties"] or {}
        # A model reached across DAGs is represented by a reference node carrying the id rather than the FK.
        if properties.get("origin") == "cross_dag_view":
            saved_query_id = properties.get("saved_query_id")
        else:
            saved_query_id = node["saved_query_id"]
        if saved_query_id:
            nodes_by_query[str(saved_query_id)].append(str(node["id"]))
            query_by_node[str(node["id"])] = str(saved_query_id)

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
            # One model can hold a node per DAG, so a read of it demands every node that stands for it.
            if (query_id := query_by_node.get(node_id)) is not None:
                stack.extend(sibling for sibling in nodes_by_query[query_id] if sibling != node_id)

    for batch in batched(demand_by_node, UPDATE_BATCH_SIZE, strict=False):
        Node.objects.filter(team_id=team_id, id__in=batch).update(
            last_demand_at=Greatest(
                F("last_demand_at"),
                Case(
                    *(When(id=node_id, then=Value(demand_by_node[node_id])) for node_id in batch),
                    output_field=DateTimeField(),
                ),
            )
        )

    return len(demand_by_node)
