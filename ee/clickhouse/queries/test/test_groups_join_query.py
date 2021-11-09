import pytest

from ee.clickhouse.queries.groups_join_query import GroupsJoinQuery
from posthog.models.filters import Filter


def test_groups_join_query_blank():
    filter = Filter(data={"properties": []})

    assert GroupsJoinQuery(filter, 2).get_join_query() == ("", {})


def test_groups_join_query_filtering(snapshot):
    filter = Filter(
        data={"properties": [{"key": "industry", "value": "finance", "type": "group", "group_type_index": 0}]}
    )

    assert GroupsJoinQuery(filter, 2).get_join_query() == snapshot
