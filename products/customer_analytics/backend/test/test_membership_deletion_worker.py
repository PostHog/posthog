import asyncio
import traceback
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from dataclasses import field
from typing import TypeVar, cast
from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from clickhouse_driver import Client
from clickhouse_driver.errors import ServerException
from parameterized import parameterized
from personhog.types.v1 import person_pb2
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.testing import ActivityEnvironment

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster, ConnectionInfo, FuturesMap, HostInfo
from posthog.dataclasses import frozen
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.deletion_targets import UnsweptRowsError
from posthog.models.person.util import DistinctIdForPerson, PersonTombstone
from posthog.personhog_client.fake_client import FakePersonHogClient, fake_personhog_client

from products.customer_analytics.backend.facade.membership_deletion_contracts import (
    MembershipDeletionInput,
    MembershipDeletionKind,
    MembershipDeletionPage,
    MembershipDeletionReference,
)
from products.customer_analytics.backend.logic import membership_deletion_receipts
from products.customer_analytics.backend.logic.membership_deletion import (
    MembershipDeletionPending,
    discover_team_deletions,
    process_membership_deletion,
    recover_prepared_deletions,
)
from products.customer_analytics.backend.logic.membership_deletion_receipts import (
    confirm_membership_deletion,
    get_membership_deletion,
    list_membership_deletion_identities,
    prepare_membership_deletion,
    record_person_membership_deletion,
    register_membership_deletion_team,
)
from products.customer_analytics.backend.temporal import membership_deletion as worker

T = TypeVar("T")
TEAM = 98765101
OTHER_TEAM = 98765102
MEMBERSHIP = "sharded_person_group_membership"
CONFIG = "person_group_membership_config"
ALL_TABLES = frozenset({MEMBERSHIP, "person_group_membership", CONFIG, "distributed_person_group_membership_config"})
_HOST = HostInfo(ConnectionInfo("fake", None), 1, 1, None, None)


@frozen(frozen=False)
class _FakeClickHouse:
    tables: frozenset[str] = ALL_TABLES
    membership: list[tuple[int, int, str, str]] = field(default_factory=list)
    config: list[int] = field(default_factory=list)
    ignore_deletes: bool = False
    failing_delete: bool = False
    deletes: int = 0

    @staticmethod
    def _matches(team_id: int, distinct_id: str | None, parameters: Mapping[str, object]) -> bool:
        if "team_ids" in parameters:
            return team_id in cast(list[int], parameters["team_ids"])
        return team_id == parameters["team_id"] and distinct_id in cast(list[str], parameters["distinct_ids"])

    def execute(
        self, sql: str, parameters: Mapping[str, object] | None = None, settings: Mapping[str, str] | None = None
    ) -> list[tuple[object, ...]]:
        parameters = parameters or {}
        if "system.tables" in sql:
            return [(int(parameters["name"] in self.tables),)]
        if "system.mutations" in sql:
            return [(0,)]
        config = CONFIG in sql
        if sql.startswith("DELETE"):
            self.deletes += 1
            if self.failing_delete:
                raise ServerException(f"DB::Exception: cannot delete {parameters!r}", code=62)
            if not self.ignore_deletes:
                if config:
                    self.config = [team for team in self.config if not self._matches(team, None, parameters)]
                else:
                    self.membership = [row for row in self.membership if not self._matches(row[0], row[3], parameters)]
            return []
        if sql.startswith("SELECT count()"):
            if config:
                return [(sum(self._matches(team, None, parameters) for team in self.config),)]
            return [(sum(self._matches(row[0], row[3], parameters) for row in self.membership),)]
        after = cast(tuple[int, str, str], parameters.get("after", (-1, "", "")))
        rows = sorted(row[1:] for row in self.membership if row[0] == parameters["team_id"] and row[1:] > after)
        return list(rows[: cast(int, parameters["limit"])])

    def remaining(self, team_id: int) -> list[str]:
        return sorted({row[3] for row in self.membership if row[0] == team_id})


class _FakeCluster:
    shard_role = NodeRole.DATA

    def __init__(self, clickhouse: _FakeClickHouse) -> None:
        self._client = cast(Client, clickhouse)

    @property
    def data_cluster_name(self) -> str:
        return settings.CLICKHOUSE_AUX_CLUSTER

    def any_host_by_role(self, fn: Callable[[Client], T], node_role: NodeRole) -> "Future[T]":
        future: Future[T] = Future()
        try:
            future.set_result(fn(self._client))
        except Exception as error:
            future.set_exception(error)
        return future

    def map_hosts_by_role(self, fn: Callable[[Client], T], node_role: NodeRole) -> FuturesMap[HostInfo, T]:
        return FuturesMap({_HOST: self.any_host_by_role(fn, node_role)})

    def map_one_host_per_shard(self, fn: Callable[[Client], T]) -> FuturesMap[HostInfo, T]:
        return self.map_hosts_by_role(fn, NodeRole.DATA)


def _cluster(clickhouse: _FakeClickHouse) -> ClickhouseCluster:
    return cast(ClickhouseCluster, _FakeCluster(clickhouse))


def _tombstone(person_uuid: UUID, *distinct_ids: str) -> PersonTombstone:
    return PersonTombstone(
        uuid=person_uuid, version=3, distinct_ids=[DistinctIdForPerson(id=value, version=2) for value in distinct_ids]
    )


def _membership(*distinct_ids: str, team_id: int = TEAM) -> list[tuple[int, int, str, str]]:
    return [(team_id, 0, f"account-{index % 2}", value) for index, value in enumerate(distinct_ids)]


class TestMembershipDeletionWorker(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        for team_id in (TEAM, OTHER_TEAM, self.team.id):
            register_membership_deletion_team(team_id)

    def _person_receipt(self, *distinct_ids: str) -> UUID:
        return record_person_membership_deletion(TEAM, f"request-{uuid4()}", _tombstone(uuid4(), *distinct_ids))

    def _confirmed(self, team_id: int, kind: MembershipDeletionKind) -> UUID:
        receipt_id = prepare_membership_deletion(team_id, kind, f"request-{uuid4()}")
        confirm_membership_deletion(team_id, receipt_id)
        return receipt_id

    def _owner(self, fake: FakePersonHogClient, *distinct_ids: str) -> None:
        fake.add_person(team_id=TEAM, person_id=7, uuid=str(uuid4()), distinct_ids=list(distinct_ids))

    def test_person_receipt_erases_unowned_identities_across_pages_and_keeps_reassigned_ones(self) -> None:
        recorded = [f"synthetic-{index:03}" for index in range(260)]
        clickhouse = _FakeClickHouse(
            membership=[*_membership(*recorded, "unrelated"), *_membership("synthetic-000", team_id=OTHER_TEAM)]
        )
        receipt_id = self._person_receipt(*recorded)
        pages: list[int] = []
        with fake_personhog_client() as fake:
            self._owner(fake, "synthetic-259")
            process_membership_deletion(_cluster(clickhouse), TEAM, receipt_id, on_page=pages.append)
            lookups = fake.assert_called("get_persons_by_distinct_ids_in_team", times=2)

        assert clickhouse.remaining(TEAM) == ["synthetic-259", "unrelated"]
        assert clickhouse.remaining(OTHER_TEAM) == ["synthetic-000"]
        assert len(pages) == 1
        assert all(len(call.request.distinct_ids) <= 250 for call in lookups)
        assert "properties" not in lookups[0].request.read_options.field_mask
        assert get_membership_deletion(TEAM, receipt_id).completed
        assert list_membership_deletion_identities(TEAM, receipt_id).identities == ()

    @parameterized.expand([("rows_survive", True, False), ("clickhouse_error", False, True)])
    def test_failed_erasure_keeps_receipt_and_hides_identifiers(
        self, _name: str, ignore_deletes: bool, failing_delete: bool
    ) -> None:
        clickhouse = _FakeClickHouse(
            membership=_membership("secret-person@example.com"),
            ignore_deletes=ignore_deletes,
            failing_delete=failing_delete,
        )
        receipt_id = self._person_receipt("secret-person@example.com")

        with fake_personhog_client(), self.assertRaises(Exception) as raised:
            process_membership_deletion(_cluster(clickhouse), TEAM, receipt_id)

        assert "secret-person" not in "".join(traceback.format_exception(raised.exception))
        if ignore_deletes:
            assert isinstance(raised.exception, UnsweptRowsError)
        assert not get_membership_deletion(TEAM, receipt_id).completed
        assert len(list_membership_deletion_identities(TEAM, receipt_id).identities) == 1

    def test_team_receipt_waits_for_verified_team_deletion_then_removes_only_that_team(self) -> None:
        clickhouse = _FakeClickHouse(
            membership=[*_membership("a", "b"), *_membership("a", team_id=OTHER_TEAM)], config=[TEAM, OTHER_TEAM]
        )
        receipt_id = self._confirmed(TEAM, MembershipDeletionKind.TEAM)

        with self.assertRaises(MembershipDeletionPending):
            process_membership_deletion(_cluster(clickhouse), TEAM, receipt_id)
        assert clickhouse.deletes == 0

        AsyncDeletion.objects.create(deletion_type=DeletionType.Team, team_id=TEAM, key=str(TEAM))
        process_membership_deletion(_cluster(clickhouse), TEAM, receipt_id)

        assert clickhouse.remaining(TEAM) == []
        assert clickhouse.config == [OTHER_TEAM]
        assert clickhouse.remaining(OTHER_TEAM) == ["a"]
        assert get_membership_deletion(TEAM, receipt_id).completed

    def test_team_persons_receipt_keeps_config_and_active_owners(self) -> None:
        clickhouse = _FakeClickHouse(
            membership=[*_membership("gone", "active"), *_membership("gone", team_id=OTHER_TEAM)], config=[TEAM]
        )
        receipt_id = self._confirmed(TEAM, MembershipDeletionKind.TEAM_PERSONS)

        with fake_personhog_client() as fake:
            self._owner(fake, "active")
            process_membership_deletion(_cluster(clickhouse), TEAM, receipt_id)

        assert clickhouse.remaining(TEAM) == ["active"]
        assert clickhouse.remaining(OTHER_TEAM) == ["gone"]
        assert clickhouse.config == [TEAM]
        assert get_membership_deletion(TEAM, receipt_id).completed

    @parameterized.expand([(kind,) for kind in MembershipDeletionKind])
    def test_missing_membership_tables_complete_without_deleting(self, kind: MembershipDeletionKind) -> None:
        clickhouse = _FakeClickHouse(tables=frozenset())
        AsyncDeletion.objects.create(deletion_type=DeletionType.Team, team_id=TEAM, key=str(TEAM))
        if kind == MembershipDeletionKind.PERSON:
            receipt_id = self._person_receipt("a")
        else:
            receipt_id = self._confirmed(TEAM, kind)

        with fake_personhog_client():
            process_membership_deletion(_cluster(clickhouse), TEAM, receipt_id)

        assert clickhouse.deletes == 0
        assert get_membership_deletion(TEAM, receipt_id).completed

    def test_recovery_confirms_only_positive_evidence_and_isolates_failures(self) -> None:
        tombstoned, live, failing = uuid4(), uuid4(), uuid4()
        tombstoned_receipt = prepare_membership_deletion(TEAM, MembershipDeletionKind.PERSON, "a", tombstoned)
        live_receipt = prepare_membership_deletion(TEAM, MembershipDeletionKind.PERSON, "b", live)
        failing_receipt = prepare_membership_deletion(OTHER_TEAM, MembershipDeletionKind.PERSON, "c", failing)
        unverified_team = prepare_membership_deletion(self.team.id, MembershipDeletionKind.TEAM, "d")
        team_persons = prepare_membership_deletion(TEAM, MembershipDeletionKind.TEAM_PERSONS, "e")
        AsyncDeletion.objects.create(deletion_type=DeletionType.Team, team_id=OTHER_TEAM, key=str(OTHER_TEAM))
        AsyncDeletion.objects.create(deletion_type=DeletionType.Team, team_id=self.team.id, key=str(self.team.id))
        AsyncDeletion.objects.create(deletion_type=DeletionType.Team, team_id=98765199, key="98765199")

        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=TEAM,
                person_id=1,
                uuid=str(tombstoned),
                is_deleted=True,
                distinct_ids=["x"],
                tombstoned_distinct_ids=["x"],
            )
            fake.add_person(team_id=TEAM, person_id=2, uuid=str(live), distinct_ids=["y"])
            original = fake.get_person_tombstones

            def flaky(
                request: person_pb2.GetPersonTombstonesRequest, timeout: float | None = None
            ) -> person_pb2.GetPersonTombstonesResponse:
                if request.team_id == OTHER_TEAM:
                    raise RuntimeError("unavailable")
                return original(request, timeout)

            with patch.object(fake, "get_person_tombstones", side_effect=flaky):
                assert recover_prepared_deletions(None) is None
            assert discover_team_deletions(0) is None

        assert get_membership_deletion(TEAM, tombstoned_receipt).confirmed
        assert [
            row.identity.distinct_id for row in list_membership_deletion_identities(TEAM, tombstoned_receipt).identities
        ] == ["x"]
        for team_id, receipt_id in (
            (TEAM, live_receipt),
            (OTHER_TEAM, failing_receipt),
            (self.team.id, unverified_team),
            (TEAM, team_persons),
        ):
            assert not get_membership_deletion(team_id, receipt_id).confirmed
        discovered = prepare_membership_deletion(
            OTHER_TEAM,
            MembershipDeletionKind.TEAM,
            f"async_deletion:{AsyncDeletion.objects.get(team_id=OTHER_TEAM).id}",
        )
        assert get_membership_deletion(OTHER_TEAM, discovered).confirmed


@frozen(frozen=False)
class _FakeTemporal:
    outcomes: dict[UUID, Exception | None]
    started: list[tuple[str, MembershipDeletionInput]] = field(default_factory=list)

    async def start_workflow(self, workflow: str, arg: MembershipDeletionInput, **options: object) -> None:
        self.started.append((str(options["id"]), arg))
        if outcome := self.outcomes[arg.receipt_id]:
            raise outcome


class TestMembershipDeletionDispatch(SimpleTestCase):
    def test_dispatch_isolates_failed_starts_and_respects_the_cap(self) -> None:
        failing, running, fresh, capped = uuid4(), uuid4(), uuid4(), uuid4()
        temporal = _FakeTemporal(
            outcomes={
                failing: RuntimeError("unavailable"),
                running: WorkflowAlreadyStartedError("id", "type"),
                fresh: None,
                capped: None,
            }
        )
        page = MembershipDeletionPage(
            receipts=tuple(
                MembershipDeletionReference(id=receipt_id, team_id=TEAM, kind=MembershipDeletionKind.PERSON)
                for receipt_id in (failing, running, fresh, capped)
            ),
            next_cursor=None,
        )

        async def dispatch() -> worker.MembershipDeletionDispatch:
            return await ActivityEnvironment().run(
                worker.membership_deletion_dispatch_activity,
                worker.MembershipDeletionDispatchInput(after=None, limit=1),
            )

        with (
            patch.object(worker, "async_connect", return_value=temporal),
            patch.object(membership_deletion_receipts, "list_pending_membership_deletions", return_value=page),
            patch.object(membership_deletion_receipts, "list_claimed_membership_deletions", return_value=()),
            patch.object(membership_deletion_receipts, "claim_membership_deletion", return_value=True),
        ):
            result = asyncio.run(dispatch())

        assert result.started == 1
        assert result.next_cursor is None
        assert [arg.receipt_id for _, arg in temporal.started] == [failing, running, fresh]
        assert temporal.started[2] == (
            worker.membership_deletion_workflow_id(fresh),
            MembershipDeletionInput(team_id=TEAM, receipt_id=fresh),
        )
