from datetime import datetime, timedelta
import pytest
from clickhouse_driver import Client
from dags.delete_groups import (
    delete_groups_job,
)
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.models.group.sql import GROUPS_TABLE


@pytest.mark.django_db
def test_full_job(cluster: ClickhouseCluster):
    timestamp = datetime.now().replace(microsecond=0)
    group_count = 100
    deleted_count = 30

    groups = [
        (i, f"key_{i}", 1, timestamp - timedelta(hours=i), 1 if i < deleted_count else 0) for i in range(group_count)
    ]

    def insert_groups(client: Client) -> None:
        client.execute(
            f"""
            INSERT INTO {GROUPS_TABLE}
            (group_type_index, group_key, team_id, created_at, is_deleted)
            VALUES
            """,
            groups,
        )

    cluster.any_host(insert_groups).result()

    def count_groups(client: Client, only_deleted: bool = False) -> int:
        where_clause = "WHERE is_deleted = 1" if only_deleted else ""
        result = client.execute(f"SELECT count() FROM {GROUPS_TABLE} {where_clause}")
        return result[0][0] if result else 0

    initial_total = cluster.any_host(count_groups).result()
    initial_deleted = cluster.any_host(lambda c: count_groups(c, True)).result()
    assert initial_total == group_count
    assert initial_deleted == deleted_count

    delete_groups_job.execute_in_process(
        resources={"cluster": cluster},
    )

    final_total = cluster.any_host(count_groups).result()
    final_deleted = cluster.any_host(lambda c: count_groups(c, True)).result()
    assert final_total == group_count - deleted_count
    assert final_deleted == 0
