from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from time_machine import travel
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.personhog_client.proto import (
    CONSISTENCY_LEVEL_STRONG,
    DistinctIdRow,
    GetDistinctIdRowsResponse,
    Group,
    GroupsResponse,
)

from products.customer_analytics.backend.logic.membership import MembershipKey
from products.customer_analytics.backend.logic.membership_discovery import (
    MembershipDiscoveryInput,
    MembershipDiscoveryStore,
    run_membership_discovery,
)
from products.customer_analytics.backend.models.membership_cleanup import (
    MembershipCleanupCandidate,
    MembershipCleanupScan,
)


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

    @contextmanager
    def primary_person_lookup(self, identity_state: str) -> Iterator[MagicMock]:
        row = DistinctIdRow(
            distinct_id=self.key.distinct_id, person_id=1, is_deleted=identity_state == "deleted_mapping"
        )
        if identity_state != "orphan":
            row.person_is_deleted = identity_state == "deleted_person"
        with (
            travel(self.now + timedelta(days=2), tick=False),
            patch("posthog.models.person.util._get_client") as get_client,
        ):
            lookup = get_client.return_value.get_distinct_id_rows
            lookup.return_value = GetDistinctIdRowsResponse(rows=[row])
            if identity_state == "unavailable":
                lookup.side_effect = RuntimeError("identity unavailable")
            yield lookup
            assert lookup.call_args.args[0].read_options.consistency == CONSISTENCY_LEVEL_STRONG

    @contextmanager
    def primary_group_lookup(self, group_state: str) -> Iterator[MagicMock]:
        with (
            travel(self.now + timedelta(days=2), tick=False),
            patch("products.customer_analytics.backend.logic.membership.require_personhog_client") as get_client,
        ):
            lookup = get_client.return_value.get_groups
            lookup.return_value = GroupsResponse(
                groups=[
                    Group(
                        id=1,
                        team_id=self.team.pk,
                        group_type_index=self.key.group_type_index,
                        group_key='account "north"',
                    )
                ]
                if group_state == "live"
                else []
            )
            if group_state == "unavailable":
                lookup.side_effect = RuntimeError("group lookup unavailable")
            yield lookup
            request = lookup.call_args.args[0]
            assert request.team_id == self.team.pk
            assert request.group_identifiers[0].group_key == 'account "north"'
            assert request.read_options.consistency == CONSISTENCY_LEVEL_STRONG
            assert "group_properties" not in request.read_options.field_mask

    def restore_missing_membership(self, missing_side: str, reassigned_mapping: bool) -> None:
        self.create_membership()
        if missing_side == "person":
            self.create_group()
            if reassigned_mapping:
                self.create_mapping(self.create_person(deleted=True))
        else:
            self.create_mapping(self.create_person())
        with travel(self.now, tick=False):
            run_membership_discovery(MembershipDiscoveryInput(team_id=self.team.pk), MembershipDiscoveryStore())
        if missing_side == "person":
            self.create_mapping(self.create_person(), version=2)
        else:
            self.create_group()

    def assert_membership_state(self, candidate_rows: Sequence[Mapping[str, object]], cursor: list[int | str]) -> None:
        assert list(MembershipCleanupCandidate.objects.for_team(self.team.pk).values()) == candidate_rows
        assert self.get_rows() == [(self.key.distinct_id,)]
        assert MembershipCleanupScan.objects.for_team(self.team.pk).get().cursor == cursor
