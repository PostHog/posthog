from posthog.settings import EE_AVAILABLE

if EE_AVAILABLE:
    from ee.clickhouse.queries.groups_join_query import GroupsJoinQuery
else:
    from posthog.queries.groups_join_query.groups_join_query import GroupsJoinQuery  # type: ignore  # noqa: F401
