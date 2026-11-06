from datetime import timedelta
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils import timezone

from posthog.clickhouse.client import sync_execute

from products.customer_analytics.backend.logic.membership import MembershipKey


class MembershipTestCase(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now()
        self.key = MembershipKey(group_type_index=0, group_key="example-account", distinct_id="example-person")

    def create_membership(self, key: MembershipKey | None = None, team_id: int | None = None) -> None:
        key = key or self.key
        sync_execute(
            """INSERT INTO sharded_person_group_membership
                (team_id, group_type_index, group_key, distinct_id, first_seen, last_seen) VALUES""",
            [
                (
                    team_id or self.team.pk,
                    key.group_type_index,
                    key.group_key,
                    key.distinct_id,
                    self.now - timedelta(days=120),
                    self.now,
                )
            ],
        )

    def create_person(self, *, deleted: bool = False) -> UUID:
        person_id = uuid4()
        sync_execute(
            "INSERT INTO person (id, created_at, team_id, is_deleted, version) VALUES",
            [(person_id, self.now, self.team.pk, deleted, 1)],
        )
        return person_id

    def create_mapping(
        self, person_id: UUID, *, distinct_id: str | None = None, version: int = 1, deleted: bool = False
    ) -> None:
        sync_execute(
            "INSERT INTO person_distinct_id2 (team_id, distinct_id, person_id, is_deleted, version) VALUES",
            [(self.team.pk, distinct_id or self.key.distinct_id, person_id, deleted, version)],
        )

    def create_group(self, group_key: str | None = None) -> None:
        sync_execute(
            "INSERT INTO groups (team_id, group_type_index, group_key, created_at, group_properties) VALUES",
            [(self.team.pk, self.key.group_type_index, group_key or self.key.group_key, self.now, "{}")],
        )

    def get_rows(self, team_id: int | None = None) -> list[tuple[str]]:
        return sync_execute(
            "SELECT distinct_id FROM person_group_membership WHERE team_id = %(team_id)s ORDER BY distinct_id",
            {"team_id": team_id or self.team.pk},
        )
