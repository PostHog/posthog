from dataclasses import dataclass, field
from enum import Enum


class NodeType(Enum):
    SESSION = "session"
    INTERACTION = "interaction"
    EVENT = "event"
    QUERY = "query"
    SUBQUERY = "subquery"


NODE_TYPE_WEIGHTS = {
    NodeType.SESSION: 0,
    NodeType.INTERACTION: 1,
    NodeType.EVENT: 2,
    NodeType.QUERY: 3,
    NodeType.SUBQUERY: 4,
}


@dataclass
class Node:
    type: NodeType
    data: dict
    children: list["Node"] = field(default_factory=list)

    def to_dict(self):
        return {
            "type": self.type.value,
            "data": self.data,
            "children": [node.to_dict() for node in self.children],
        }


def construct_hierarchy(session, interactions_and_events, queries) -> dict:
    """
    Constructs a tree-like hierarchy for session based on interactions and queries, to expose
    triggered-by relationships.
    """
    nodes: list[Node] = []
    nodes.extend(make_empty_node(interaction_type, data) for data in interactions_and_events)
    nodes.extend(make_empty_node(query_type, data) for data in queries)

    root_node = Node(type=NodeType.SESSION, data=session, children=[])

    # :KLUDGE: This is n^2 complexity. Could be sped up by sorting or doing other clever things.
    for node in nodes:
        potential_parents = [parent_node for parent_node in nodes if is_child(parent_node, node)]

        # Select the least specific potential parent
        if len(potential_parents) > 0:
            parent = max(potential_parents, key=lambda parent: NODE_TYPE_WEIGHTS[parent.type])
        else:
            parent = root_node
        parent.children.append(node)

    return root_node.to_dict()


def is_child(parent: Node, child: Node) -> bool:
    if parent.type == child.type:
        return False

    if parent.type == NodeType.SESSION:
        return parent.data["session_id"] == child.data["session_id"]

    if parent.type == NodeType.INTERACTION and child.type == NodeType.EVENT:
        return parent.data["primary_interaction_id"] == child.data["primary_interaction_id"]

    if parent.type == NodeType.INTERACTION and child.type == NodeType.QUERY:
        return parent.data["primary_interaction_id"] in child.data["client_query_id"]

    if parent.type == NodeType.EVENT and child.type == NodeType.QUERY:
        return parent.data["query_id"] in child.data["client_query_id"]

    if parent.type == NodeType.QUERY and child.type == NodeType.SUBQUERY:
        return parent.data["client_query_id"] == child.data["client_query_id"]

    return False


def make_empty_node(type_getter, data: dict):
    return Node(type=type_getter(data), data=data, children=[])


def interaction_type(data):
    return NodeType.INTERACTION if data["is_primary_interaction"] else NodeType.EVENT


def query_type(data):
    return NodeType.QUERY if data["is_initial_query"] else NodeType.SUBQUERY
