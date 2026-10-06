from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.utils import timezone

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models.person_group_membership.sql import (
    DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
    PERSON_GROUP_MEMBERSHIP_TABLE,
)

from products.customer_analytics.backend.logic.membership_deletion import (
    delete_distinct_ids,
    delete_teams,
    membership_cluster,
)


class TestMembershipClickHouseDeletion(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cluster = membership_cluster()
        self.other_team_id = self.team.pk + 1000000
        self.addCleanup(delete_teams, self.cluster, [self.team.pk, self.other_team_id])
        timestamp = timezone.now() - timedelta(days=1)
        sync_execute(
            f"INSERT INTO {PERSON_GROUP_MEMBERSHIP_TABLE} VALUES",
            [
                (self.team.pk, 0, "example-account", "a", timestamp, timestamp),
                (self.team.pk, 0, "example-account", "a", timestamp, timestamp),
                (self.team.pk, 0, "example-account", "alias", timestamp, timestamp),
                (self.team.pk, 0, "other-account", "unrelated", timestamp, timestamp),
                (self.other_team_id, 0, "example-account", "a", timestamp, timestamp),
            ],
            settings={"distributed_foreground_insert": 1},
        )
        sync_execute(
            f"INSERT INTO {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE} VALUES",
            [(self.team.pk, 0, 1, 1), (self.other_team_id, 0, 1, 1)],
            settings={"distributed_foreground_insert": 1},
        )

    def _ids(self, team_id: int) -> list[str]:
        return [
            row[0]
            for row in sync_execute(
                f"SELECT DISTINCT distinct_id FROM {PERSON_GROUP_MEMBERSHIP_TABLE} "
                "WHERE team_id = %(team_id)s ORDER BY distinct_id",
                {"team_id": team_id},
            )
        ]

    def test_distinct_id_deletion_removes_all_aggregate_copies_and_keeps_other_tenants(self) -> None:
        delete_distinct_ids(self.cluster, self.team.pk, ["a", "alias", "a"])
        assert self._ids(self.team.pk) == ["unrelated"]
        assert self._ids(self.other_team_id) == ["a"]
        delete_distinct_ids(self.cluster, self.team.pk, ["a", "alias"])
        assert self._ids(self.team.pk) == ["unrelated"]

    @parameterized.expand([("team_teardown", True), ("person_purge", False)])
    def test_team_deletion_clears_only_the_requested_team_and_preserves_purge_config(
        self, _name: str, include_config: bool
    ) -> None:
        delete_teams(self.cluster, [self.team.pk], include_config=include_config)
        assert self._ids(self.team.pk) == []
        assert self._ids(self.other_team_id) == ["a"]
        configs = sync_execute(
            f"SELECT team_id FROM {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE} "
            "WHERE team_id IN %(team_ids)s ORDER BY team_id",
            {"team_ids": [self.team.pk, self.other_team_id]},
        )
        assert configs == ([(self.other_team_id,)] if include_config else [(self.team.pk,), (self.other_team_id,)])
