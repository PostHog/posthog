import pytest

from posthog.queries.time_to_see_data.hierarchy import Node, NodeType, is_child


@pytest.mark.parametrize(
    "potential_parent,potential_child,expected_result",
    [
        # Sessions
        (Node(NodeType.SESSION, {"session_id": 1}), Node(NodeType.INTERACTION, {"session_id": 1}), True),
        (Node(NodeType.SESSION, {"session_id": 1}), Node(NodeType.QUERY, {"session_id": 1}), True),
        (Node(NodeType.SESSION, {"session_id": 2}), Node(NodeType.QUERY, {"session_id": 1}), False),
        (Node(NodeType.SESSION, {"session_id": 1}), Node(NodeType.SESSION, {"session_id": 1}), False),
        # Interactions
        (
            Node(NodeType.INTERACTION, {"primary_interaction_id": "1"}),
            Node(NodeType.EVENT, {"primary_interaction_id": "1"}),
            True,
        ),
        (
            Node(NodeType.INTERACTION, {"primary_interaction_id": "1"}),
            Node(NodeType.EVENT, {"primary_interaction_id": "2"}),
            False,
        ),
        (
            Node(NodeType.INTERACTION, {"primary_interaction_id": "123"}),
            Node(NodeType.QUERY, {"client_query_id": "123::2543245"}),
            True,
        ),
        (
            Node(NodeType.INTERACTION, {"primary_interaction_id": "456"}),
            Node(NodeType.QUERY, {"client_query_id": "123::2543245"}),
            False,
        ),
        (
            Node(NodeType.INTERACTION, {"primary_interaction_id": "123"}),
            Node(NodeType.SUBQUERY, {"client_query_id": "123::2543245"}),
            False,
        ),
        (Node(NodeType.INTERACTION, {"session_id": 1}), Node(NodeType.SESSION, {}), False),
        (Node(NodeType.INTERACTION, {}), Node(NodeType.INTERACTION, {}), False),
        # Events
        (
            Node(NodeType.EVENT, {"query_id": "2543245"}),
            Node(NodeType.QUERY, {"client_query_id": "123::2543245"}),
            True,
        ),
        (
            Node(NodeType.EVENT, {"query_id": "foobar"}),
            Node(NodeType.QUERY, {"client_query_id": "123::2543245"}),
            False,
        ),
        (
            Node(NodeType.EVENT, {"query_id": "2543245"}),
            Node(NodeType.SUBQUERY, {"client_query_id": "123::2543245"}),
            False,
        ),
        # Queries
        (
            Node(NodeType.QUERY, {"client_query_id": "123::2543245"}),
            Node(NodeType.SUBQUERY, {"client_query_id": "123::2543245"}),
            True,
        ),
        (
            Node(NodeType.QUERY, {"client_query_id": "123::"}),
            Node(NodeType.SUBQUERY, {"client_query_id": "123::2543245"}),
            False,
        ),
    ],
)
def test_is_child(potential_parent, potential_child, expected_result):
    assert is_child(potential_parent, potential_child) == expected_result
