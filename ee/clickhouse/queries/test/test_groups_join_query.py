from posthog.models.filters import Filter

from ee.clickhouse.queries.groups_join_query import GroupsJoinQuery


def test_groups_join_query_blank():
    filter = Filter(data={"properties": []})

    assert GroupsJoinQuery(filter, 2).get_join_query() == ("", {})


def test_groups_join_query_filtering(snapshot):
    filter = Filter(
        data={
            "properties": [
                {
                    "key": "industry",
                    "value": "finance",
                    "type": "group",
                    "group_type_index": 0,
                }
            ]
        }
    )

    assert GroupsJoinQuery(filter, 2).get_join_query() == snapshot


def test_groups_join_query_filtering_with_custom_key_names(snapshot):
    filter = Filter(
        data={
            "properties": [
                {
                    "key": "industry",
                    "value": "finance",
                    "type": "group",
                    "group_type_index": 0,
                },
                {
                    "key": "company",
                    "value": "crashed",
                    "type": "group",
                    "group_type_index": 2,
                },
            ]
        }
    )

    assert GroupsJoinQuery(filter, 2, join_key="call_me_industry").get_join_query() == snapshot


def test_groups_filter_query_with_group_key():
    """Test that $group_key property generates correct filter query"""
    filter = Filter(
        data={
            "properties": [
                {
                    "key": "$group_key",
                    "value": "workspace-123",
                    "type": "group",
                    "group_type_index": 0,
                }
            ]
        }
    )

    query, params = GroupsJoinQuery(filter, 2).get_filter_query(group_type_index=0)

    # Should contain direct comparison against group_key column
    assert "group_key = %(test_group_key_0)s" in query or "group_key =" in query
    # Should NOT contain JSON extraction
    assert "JSONExtract" not in query

    # Test with icontains operator
    filter_icontains = Filter(
        data={
            "properties": [
                {
                    "key": "$group_key",
                    "value": "workspace",
                    "operator": "icontains",
                    "type": "group",
                    "group_type_index": 0,
                }
            ]
        }
    )

    query, params = GroupsJoinQuery(filter_icontains, 2).get_filter_query(group_type_index=0)
    assert "group_key ILIKE" in query
    assert "%workspace%" in str(params.values())
