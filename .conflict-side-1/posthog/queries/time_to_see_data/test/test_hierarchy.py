import pytest

from posthog.queries.time_to_see_data.hierarchy import Node, NodeType, construct_hierarchy, is_child


@pytest.mark.parametrize(
    "potential_parent,potential_child,expected_result",
    [
        # Sessions
        (
            Node(NodeType.SESSION, {"session_id": 1}),
            Node(NodeType.INTERACTION, {"session_id": 1}),
            True,
        ),
        (
            Node(NodeType.SESSION, {"session_id": 1}),
            Node(NodeType.QUERY, {"session_id": 1}),
            True,
        ),
        (
            Node(NodeType.SESSION, {"session_id": 2}),
            Node(NodeType.QUERY, {"session_id": 1}),
            False,
        ),
        (
            Node(NodeType.SESSION, {"session_id": 1}),
            Node(NodeType.SESSION, {"session_id": 1}),
            False,
        ),
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
        (
            Node(NodeType.INTERACTION, {"session_id": 1}),
            Node(NodeType.SESSION, {}),
            False,
        ),
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


def test_construct_hierarchy():
    session = {"session_id": 1}

    interaction_1 = {
        **session,
        "is_primary_interaction": True,
        "primary_interaction_id": "123",
    }
    event_11 = {
        **session,
        "is_primary_interaction": False,
        "primary_interaction_id": "123",
        "query_id": "456",
    }
    query_111 = {**session, "client_query_id": "123::456", "is_initial_query": True}
    subquery_1111 = {
        **session,
        "client_query_id": "123::456",
        "is_initial_query": False,
    }
    event_12 = {
        **session,
        "is_primary_interaction": False,
        "primary_interaction_id": "123",
        "query_id": "789",
    }
    query_121 = {**session, "client_query_id": "123::789", "is_initial_query": True}
    query_13 = {**session, "client_query_id": "123::1111", "is_initial_query": True}

    interaction_2 = {
        **session,
        "is_primary_interaction": True,
        "primary_interaction_id": "8888",
    }

    stray_event = {
        **session,
        "is_primary_interaction": False,
        "primary_interaction_id": "efg",
        "query_id": "9999",
    }
    stray_query = {**session, "client_query_id": "foobar", "is_initial_query": True}

    result = construct_hierarchy(
        session,
        [interaction_1, event_11, event_12, interaction_2, stray_event],
        [query_111, subquery_1111, query_121, query_13, stray_query],
    )

    assert result == {
        "type": "session",
        "data": session,
        "children": [
            {
                "type": "interaction",
                "data": interaction_1,
                "children": [
                    {
                        "type": "event",
                        "data": event_11,
                        "children": [
                            {
                                "type": "query",
                                "data": query_111,
                                "children": [
                                    {
                                        "type": "subquery",
                                        "data": subquery_1111,
                                        "children": [],
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "type": "event",
                        "data": event_12,
                        "children": [{"type": "query", "data": query_121, "children": []}],
                    },
                    {"type": "query", "data": query_13, "children": []},
                ],
            },
            {
                "type": "interaction",
                "data": interaction_2,
                "children": [],
            },
            {
                "type": "event",
                "data": stray_event,
                "children": [],
            },
            {
                "type": "query",
                "data": stray_query,
                "children": [],
            },
        ],
    }
