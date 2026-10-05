from collections.abc import Sequence

from posthog.clickhouse.cluster import ClickhouseCluster, get_cluster

from products.customer_analytics.backend.logic import membership_deletion


def has_team_membership(team_id: int) -> bool:
    return membership_deletion.has_team_membership(get_cluster(), team_id)


def delete_person_membership(team_id: int, distinct_ids: Sequence[str]) -> None:
    if distinct_ids:
        membership_deletion.delete_distinct_ids(get_cluster(), team_id, distinct_ids)


def delete_team_membership(cluster: ClickhouseCluster, team_ids: Sequence[int], *, include_config: bool = True) -> None:
    membership_deletion.delete_teams(cluster, team_ids, include_config=include_config)


def removes_account_group_property(cluster: ClickhouseCluster, team_id: int, properties: Sequence[str]) -> bool:
    return membership_deletion.removes_account_group_property(cluster, team_id, properties)


def refuse_unswept_membership_sources(
    cluster: ClickhouseCluster, sources: Sequence[tuple[str, bool, str, dict[str, object]]]
) -> None:
    membership_deletion.MembershipReconciliation(cluster, "async_deletes").refuse_unswept_sources(sources)


def stage_membership_deletion(
    cluster: ClickhouseCluster,
    operation_id: str,
    sources: Sequence[tuple[str, bool, str, dict[str, object]]],
) -> None:
    membership_deletion.MembershipReconciliation(cluster, operation_id).stage(sources)


def reconcile_membership_deletion(
    cluster: ClickhouseCluster, operation_id: str, sources: Sequence[tuple[str, bool]]
) -> None:
    membership_deletion.MembershipReconciliation(cluster, operation_id).reconcile(sources)


def cleanup_membership_deletion(cluster: ClickhouseCluster, operation_id: str) -> None:
    membership_deletion.MembershipReconciliation(cluster, operation_id).cleanup()
