import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils.timezone import now

import grpc
from confluent_kafka import KafkaError
from parameterized import parameterized
from personhog.types.v1 import person_pb2

from posthog.clickhouse.client import sync_execute
from posthog.exceptions import ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut
from posthog.kafka_client.client import ClickhouseProducer, ProduceResult
from posthog.kafka_client.topics import KAFKA_PERSON
from posthog.models.person import Person
from posthog.models.person.divergence import (
    DivergentPerson,
    PersonDivergenceKind,
    PersonRef,
    RepairAction,
    RepairOutcome,
    RepairSummary,
    _WritePacer,
    repair_persons,
    scan_hidden_persons,
    scan_stale_persons,
    scan_swept_persons,
)
from posthog.models.person.util import (
    create_person as create_person_in_ch,
    tombstone_persons_in_postgres,
)
from posthog.models.signals import mute_selected_signals
from posthog.models.team import Team
from posthog.personhog_client.fake_client import get_active_fake
from posthog.test.persons import add_distinct_id, create_person

PG_PROPERTIES = {"email": "postgres@example.com"}
CH_PROPERTIES = {"email": "clickhouse@example.com"}

_PERSON_COLUMNS = (
    "id, created_at, team_id, properties, is_identified, _timestamp, _offset, is_deleted, version, last_seen_at"
)


def _rpc_error(code: grpc.StatusCode) -> grpc.RpcError:
    error = grpc.RpcError()
    error.code = MagicMock(return_value=code)  # type: ignore[attr-defined]
    return error


def _utc_naive(hours_ago: float) -> datetime:
    return (now() - timedelta(hours=hours_ago)).astimezone(UTC).replace(tzinfo=None)


class TestPersonDivergence(ClickhouseTestMixin, BaseTest):
    def _pg_person(self, *, version: int, distinct_ids: dict[str, int] | None = None) -> Person:
        # Muted signals keep create_person out of ClickHouse, so each test writes exactly the rows it describes.
        with mute_selected_signals():
            person = create_person(team=self.team, version=version, properties=PG_PROPERTIES)
            for distinct_id, distinct_id_version in (distinct_ids or {}).items():
                add_distinct_id(person=person, distinct_id=distinct_id, version=distinct_id_version)
        return person

    def _ch_person_row(
        self,
        person_uuid: UUID | str,
        version: int,
        *,
        deleted: bool = False,
        hours_ago: float = 0,
        team_id: int | None = None,
    ) -> None:
        create_person_in_ch(
            team_id=team_id or self.team.pk,
            uuid=str(person_uuid),
            version=version,
            is_deleted=deleted,
            properties=CH_PROPERTIES,
            timestamp=now() - timedelta(hours=hours_ago),
        )

    def _stop_person_merges(self) -> None:
        # A background merge collapses the older rows that the stale and swept shapes are made of.
        sync_execute("SYSTEM STOP MERGES person")
        self.addCleanup(sync_execute, "SYSTEM START MERGES person")

    def _swept_rows(self, rows_by_person: dict[UUID, list[tuple[int, bool, float]]]) -> None:
        # Stopped merges also block lightweight deletes, which run as mutations, so the rows are deleted
        # in a one-part side table whose part is then attached to person.
        self._stop_person_merges()
        staging = f"person_divergence_swept_{self.team.pk}"
        sync_execute(f"DROP TABLE IF EXISTS {staging} SYNC")
        sync_execute(f"CREATE TABLE {staging} AS person ENGINE = ReplacingMergeTree(version) ORDER BY (team_id, id)")
        self.addCleanup(sync_execute, f"DROP TABLE IF EXISTS {staging} SYNC")
        sync_execute(
            f"INSERT INTO {staging} ({_PERSON_COLUMNS}) VALUES",
            [
                {
                    "id": person_uuid,
                    "created_at": _utc_naive(24),
                    "team_id": self.team.pk,
                    "properties": json.dumps(CH_PROPERTIES),
                    "is_identified": 0,
                    "_timestamp": _utc_naive(hours_ago),
                    "_offset": 0,
                    "is_deleted": int(deleted),
                    "version": version,
                    "last_seen_at": _utc_naive(24),
                }
                for person_uuid, rows in rows_by_person.items()
                for version, deleted, hours_ago in rows
            ],
            settings={"optimize_on_insert": 0},
            flush=False,
        )
        sync_execute(f"DELETE FROM {staging} WHERE 1", settings={"lightweight_deletes_sync": 2})
        sync_execute(f"ALTER TABLE person ATTACH PARTITION tuple() FROM {staging}")

    def _ch_person(self, person_uuid: UUID | str) -> tuple[int, int, dict[str, Any]]:
        [[deleted, version, properties]] = sync_execute(
            """
            SELECT argMax(is_deleted, version), max(version), argMax(properties, version)
            FROM person WHERE team_id = %(team_id)s AND id = %(person_uuid)s
            """,
            {"team_id": self.team.pk, "person_uuid": str(person_uuid)},
        )
        return int(deleted), int(version), json.loads(properties)

    def _pg_version(self, person: Person) -> int:
        stored = get_active_fake().stored_person(self.team.pk, str(person.uuid))
        assert stored is not None
        return stored.version

    def _ch_last_seen_at(self, person_uuid: UUID | str) -> datetime | None:
        # argMax skips NULL values, so read the newest row itself.
        [[last_seen_at]] = sync_execute(
            """
            SELECT last_seen_at FROM person WHERE team_id = %(team_id)s AND id = %(person_uuid)s
            ORDER BY version DESC LIMIT 1
            """,
            {"team_id": self.team.pk, "person_uuid": str(person_uuid)},
        )
        return last_seen_at

    def _repair(
        self, *person_uuids: UUID | str, apply: bool = True, include_stale: bool = False
    ) -> tuple[RepairSummary, list[RepairAction]]:
        actions: list[RepairAction] = []
        summary = repair_persons(
            [PersonRef(team_id=self.team.pk, person_uuid=str(u)) for u in person_uuids],
            apply=apply,
            include_stale=include_stale,
            on_action=actions.append,
            log=lambda _: None,
        )
        return summary, actions

    def _action(
        self,
        person_uuid: UUID | str,
        outcome: RepairOutcome,
        *,
        kind: PersonDivergenceKind | None = None,
        pg_version: int | None = None,
        ch_max_version: int | None = None,
        target_version: int | None = None,
    ) -> RepairAction:
        return RepairAction(
            team_id=self.team.pk,
            person_uuid=str(person_uuid),
            kind=kind,
            pg_version=pg_version,
            ch_max_version=ch_max_version,
            target_version=target_version,
            outcome=outcome,
        )

    def _team_scan_range(self) -> dict[str, int]:
        return {"min_team_id": self.team.pk, "max_team_id": self.team.pk + 1}

    def test_hidden_scan_reports_only_persons_live_in_postgres_behind_a_legacy_tombstone(self) -> None:
        hidden = self._pg_person(version=3)
        self._ch_person_row(hidden.uuid, 3)
        self._ch_person_row(hidden.uuid, 103, deleted=True)
        tombstoned = self._pg_person(version=3)
        tombstone_persons_in_postgres(self.team.pk, [tombstoned.uuid])
        self._ch_person_row(tombstoned.uuid, 103, deleted=True)
        self._ch_person_row(uuid4(), 103, deleted=True)
        current_tombstone = self._pg_person(version=3)
        self._ch_person_row(current_tombstone.uuid, 4, deleted=True)
        revived = self._pg_person(version=104)
        self._ch_person_row(revived.uuid, 103, deleted=True)
        self._ch_person_row(revived.uuid, 104)

        found: list[DivergentPerson] = []
        summary = scan_hidden_persons(**self._team_scan_range(), on_found=found.append, log=lambda _: None)

        assert found == [
            DivergentPerson(
                team_id=self.team.pk, person_uuid=str(hidden.uuid), kind="hidden", ch_max_version=103, pg_version=3
            )
        ]
        assert (summary.candidates, summary.divergent, summary.skipped_team_ids) == (3, 1, [])

    def test_swept_scan_reports_live_persons_whose_late_live_row_was_swept_with_the_tombstone(self) -> None:
        swept = self._pg_person(version=3)
        live_row_before_the_tombstone = self._pg_person(version=3)
        revived_after_the_sweep = self._pg_person(version=104)
        self._swept_rows(
            {
                swept.uuid: [(3, False, 3), (103, True, 2), (4, False, 1)],
                live_row_before_the_tombstone.uuid: [(3, False, 3), (103, True, 2)],
                revived_after_the_sweep.uuid: [(103, True, 2), (4, False, 1)],
            }
        )
        self._ch_person_row(revived_after_the_sweep.uuid, 104)

        found: list[DivergentPerson] = []
        summary = scan_swept_persons(**self._team_scan_range(), on_found=found.append, log=lambda _: None)

        assert found == [
            DivergentPerson(
                team_id=self.team.pk, person_uuid=str(swept.uuid), kind="swept", ch_max_version=103, pg_version=3
            )
        ]
        assert (summary.candidates, summary.divergent) == (1, 1)

    def test_stale_scan_reports_only_a_live_winner_above_postgres_with_a_late_lower_row(self) -> None:
        self._stop_person_merges()
        stale = self._pg_person(version=5)
        in_sync = self._pg_person(version=10)
        deleted_winner = self._pg_person(version=5)
        quick_retry = self._pg_person(version=5)
        for person in (stale, in_sync, deleted_winner):
            self._ch_person_row(person.uuid, 10, deleted=person is deleted_winner, hours_ago=3)
            self._ch_person_row(person.uuid, 5, hours_ago=1)
        self._ch_person_row(quick_retry.uuid, 10, hours_ago=1.5)
        self._ch_person_row(quick_retry.uuid, 5, hours_ago=1)

        found: list[DivergentPerson] = []
        summary = scan_stale_persons(
            window_days=60, **self._team_scan_range(), on_found=found.append, log=lambda _: None
        )

        assert found == [
            DivergentPerson(
                team_id=self.team.pk, person_uuid=str(stale.uuid), kind="stale", ch_max_version=10, pg_version=5
            )
        ]
        assert (summary.candidates, summary.divergent) == (2, 1)

    # ── Repair ───────────────────────────────────────────────────────

    def _divergent_person(self, case: str) -> Person:
        if case == "hidden":
            person = self._pg_person(version=3)
            self._ch_person_row(person.uuid, 3)
            self._ch_person_row(person.uuid, 103, deleted=True)
        elif case == "hidden_after_an_undelivered_publish":
            person = self._pg_person(version=104)
            self._ch_person_row(person.uuid, 103, deleted=True)
        elif case == "stale":
            person = self._pg_person(version=5)
            self._ch_person_row(person.uuid, 10)
            self._ch_person_row(person.uuid, 5)
        elif case == "swept":
            person = self._pg_person(version=3)
            self._swept_rows({person.uuid: [(103, True, 2), (4, False, 1)]})
        elif case == "behind":
            person = self._pg_person(version=7)
            self._ch_person_row(person.uuid, 5)
        else:
            person = self._pg_person(version=3)
        return person

    @parameterized.expand(
        [
            ("hidden", "hidden", 3, 103, 104),
            ("hidden_after_an_undelivered_publish", "hidden", 104, 103, 104),
            ("stale", "stale", 5, 10, 11),
            ("swept", "swept", 3, 103, 104),
            ("behind", "behind", 7, 5, 7),
            ("absent", "absent", 3, None, 3),
        ]
    )
    def test_republishes_a_divergent_person_live_one_version_above_clickhouse(
        self, case: str, kind: PersonDivergenceKind, pg_version: int, ch_max_version: int | None, target_version: int
    ) -> None:
        person = self._divergent_person(case)

        summary, actions = self._repair(person.uuid, include_stale=True)

        assert actions == [
            self._action(
                person.uuid,
                "repaired",
                kind=kind,
                pg_version=pg_version,
                ch_max_version=ch_max_version,
                target_version=target_version,
            )
        ]
        assert (summary.persons, summary.undelivered) == (1, 0)
        assert self._pg_version(person) == target_version
        assert self._ch_person(person.uuid) == (0, target_version, PG_PROPERTIES)
        # Postgres has no last_seen_at for this person, and ingestion publishes that as null.
        assert self._ch_last_seen_at(person.uuid) is None

    @parameterized.expand([("dry_run", False), ("apply", True)])
    def test_repairs_a_hidden_person_only_when_applied(self, _name: str, apply: bool) -> None:
        person = self._pg_person(version=3)
        self._ch_person_row(person.uuid, 3)
        self._ch_person_row(person.uuid, 103, deleted=True)

        summary, actions = self._repair(person.uuid, apply=apply)

        outcome: RepairOutcome = "repaired" if apply else "would_repair"
        assert actions == [
            self._action(person.uuid, outcome, kind="hidden", pg_version=3, ch_max_version=103, target_version=104),
        ]
        assert summary.applied is apply
        if apply:
            assert self._pg_version(person) == 104
            assert self._ch_person(person.uuid) == (0, 104, PG_PROPERTIES)
        else:
            get_active_fake().assert_not_called("set_person_version_floor")
            assert self._pg_version(person) == 3
            assert self._ch_person(person.uuid) == (1, 103, CH_PROPERTIES)

    @parameterized.expand([("dry_run", False, []), ("apply", True, [1.0])])
    def test_throttles_on_each_divergent_row_written(self, _name: str, apply: bool, sleeps: list[float]) -> None:
        person = self._pg_person(version=3)
        self._ch_person_row(person.uuid, 103, deleted=True)
        other = self._pg_person(version=3)
        self._ch_person_row(other.uuid, 103, deleted=True)

        with patch("posthog.models.person.divergence.time") as clock:
            clock.monotonic.return_value = 0.0
            repair_persons(
                [PersonRef(team_id=self.team.pk, person_uuid=str(p.uuid)) for p in (person, other)],
                apply=apply,
                max_writes_per_second=1,
                on_action=lambda _: None,
                log=lambda _: None,
            )

        assert [c.args[0] for c in clock.sleep.call_args_list] == sleeps

    def test_publishes_the_properties_postgres_holds_after_the_raise(self) -> None:
        person = self._divergent_person("hidden")
        fake = get_active_fake()
        raise_floor = fake.set_person_version_floor
        updated = {"email": "updated@example.com"}

        def ingestion_update_then_raise(
            request: person_pb2.SetPersonVersionFloorRequest, timeout: float | None = None
        ) -> person_pb2.SetPersonVersionFloorResponse:
            stored = fake.stored_person(self.team.pk, str(person.uuid))
            assert stored is not None
            stored.properties = json.dumps(updated).encode()
            stored.version += 1
            return raise_floor(request, timeout)

        with patch.object(fake, "set_person_version_floor", side_effect=ingestion_update_then_raise):
            self._repair(person.uuid)

        assert self._ch_person(person.uuid) == (0, 104, updated)

    def test_a_failed_kafka_delivery_counts_as_undelivered(self) -> None:
        person = self._divergent_person("hidden")
        failed = ProduceResult(topic=KAFKA_PERSON)
        failed.set_result(KafkaError(-192, "Local: Message timed out"), None)

        with patch.object(ClickhouseProducer, "produce", return_value=failed):
            summary, actions = self._repair(person.uuid)

        assert [a.outcome for a in actions] == ["repaired"]
        assert summary.undelivered == 1

    @parameterized.expand(
        [
            ("replica_catches_up_on_the_third_reread", 3, "repaired", [0.025, 0.05]),
            ("replica_never_catches_up", None, "skipped_reread_lagging", [0.025, 0.05, 0.1, 0.15, 0.175]),
        ]
    )
    def test_rereads_until_the_replica_shows_the_raise(
        self, _name: str, caught_up_on_reread: int | None, outcome: RepairOutcome, sleeps: list[float]
    ) -> None:
        person = self._divergent_person("hidden")
        fake = get_active_fake()
        read = fake.get_persons_by_uuids
        raised_to: list[int] = []
        rereads = 0

        def primary_only_raise(
            request: person_pb2.SetPersonVersionFloorRequest, timeout: float | None = None
        ) -> person_pb2.SetPersonVersionFloorResponse:
            raised_to.append(request.min_version)
            return person_pb2.SetPersonVersionFloorResponse(updated=True)

        def lagging_replica(request: person_pb2.GetPersonsByUuidsRequest) -> person_pb2.PersonsResponse:
            nonlocal rereads
            if raised_to:
                rereads += 1
                if rereads == caught_up_on_reread:
                    stored = fake.stored_person(self.team.pk, str(person.uuid))
                    assert stored is not None
                    stored.version = raised_to[0]
            return read(request)

        with (
            patch.object(fake, "set_person_version_floor", side_effect=primary_only_raise),
            patch.object(fake, "get_persons_by_uuids", side_effect=lagging_replica),
            patch("posthog.models.person.divergence._sleep") as sleep,
        ):
            _, actions = self._repair(person.uuid)

        assert [a.outcome for a in actions] == [outcome]
        assert [c.args[0] for c in sleep.call_args_list] == sleeps
        if outcome == "repaired":
            assert self._ch_person(person.uuid) == (0, 104, PG_PROPERTIES)
        else:
            assert self._ch_person(person.uuid) == (1, 103, CH_PROPERTIES)

    @parameterized.expand(
        [
            ("clickhouse_timeout_while_planning", "planning", ClickHouseQueryTimeOut()),
            ("personhog_internal_error_on_the_raise", "raise", grpc.StatusCode.INTERNAL),
            ("personhog_unavailable_on_the_raise", "raise", grpc.StatusCode.UNAVAILABLE),
        ]
    )
    def test_retries_a_transient_error_and_counts_the_person_once(
        self, _name: str, step: str, error: Exception | grpc.StatusCode
    ) -> None:
        person = self._divergent_person("hidden")
        failure = _rpc_error(error) if isinstance(error, grpc.StatusCode) else error

        with self._failing_once(step, failure), patch("posthog.models.person.divergence._sleep") as sleep:
            summary, actions = self._repair(person.uuid)

        assert [a.outcome for a in actions] == ["repaired"]
        assert summary.person_outcomes == {"repaired": 1}
        assert [c.args[0] for c in sleep.call_args_list] == [1.0]
        assert self._ch_person(person.uuid) == (0, 104, PG_PROPERTIES)

    @parameterized.expand(
        [
            ("non_transient_error_is_not_retried", ValueError("bad request"), 1, []),
            ("transient_error_on_every_attempt_stops_after_three", _rpc_error(grpc.StatusCode.INTERNAL), 3, [1.0, 2.0]),
        ]
    )
    def test_stops_the_run_on_an_error_that_does_not_clear(
        self, _name: str, failure: Exception, attempts: int, sleeps: list[float]
    ) -> None:
        person = self._divergent_person("hidden")
        fake = get_active_fake()

        with (
            patch.object(fake, "set_person_version_floor", side_effect=failure) as raise_floor,
            patch("posthog.models.person.divergence._sleep") as sleep,
        ):
            with self.assertRaises(type(failure)):
                self._repair(person.uuid)

        assert raise_floor.call_count == attempts
        assert [c.args[0] for c in sleep.call_args_list] == sleeps

    def _failing_once(self, step: str, failure: Exception) -> Any:
        fake = get_active_fake()
        if step == "planning":
            query = sync_execute
            failed: list[bool] = []

            def ch_fails_once(*args: Any, **kwargs: Any) -> Any:
                if not failed:
                    failed.append(True)
                    raise failure
                return query(*args, **kwargs)

            return patch("posthog.models.person.divergence.sync_execute", side_effect=ch_fails_once)
        raise_floor = fake.set_person_version_floor
        calls: list[bool] = []

        def raise_fails_once(
            request: person_pb2.SetPersonVersionFloorRequest, timeout: float | None = None
        ) -> person_pb2.SetPersonVersionFloorResponse:
            if not calls:
                calls.append(True)
                raise failure
            return raise_floor(request, timeout)

        return patch.object(fake, "set_person_version_floor", side_effect=raise_fails_once)

    def _skipped_person(self, case: str) -> UUID:
        if case == "in_sync":
            person = self._pg_person(version=3)
            self._ch_person_row(person.uuid, 3)
            return person.uuid
        if case == "tombstoned_in_postgres":
            person = self._pg_person(version=3)
            tombstone_persons_in_postgres(self.team.pk, [person.uuid])
            self._ch_person_row(person.uuid, 103, deleted=True)
            return person.uuid
        if case == "stale_without_include_stale":
            return self._divergent_person("stale").uuid
        absent = uuid4()
        self._ch_person_row(absent, 103, deleted=True)
        return absent

    @parameterized.expand(
        [
            ("in_sync", ["skipped_not_divergent"]),
            ("tombstoned_in_postgres", ["skipped_not_live"]),
            ("absent_from_postgres", ["skipped_not_live"]),
            ("stale_without_include_stale", ["skipped_stale"]),
        ]
    )
    def test_leaves_a_person_alone_unless_it_is_live_in_postgres_and_divergent(
        self, case: str, outcomes: list[str]
    ) -> None:
        person_uuid = self._skipped_person(case)
        before = self._ch_person(person_uuid)

        _, actions = self._repair(person_uuid)

        assert [a.outcome for a in actions] == outcomes
        get_active_fake().assert_not_called("set_person_version_floor")
        assert self._ch_person(person_uuid) == before

    def test_skips_every_person_of_a_team_that_no_longer_exists(self) -> None:
        missing_team_id = self.team.pk + 1_000_000
        assert not Team.objects.filter(pk=missing_team_id).exists()
        person_uuid = str(uuid4())
        get_active_fake().add_person(team_id=missing_team_id, person_id=987654, uuid=person_uuid, version=3)
        self._ch_person_row(person_uuid, 3, team_id=missing_team_id)
        self._ch_person_row(person_uuid, 103, deleted=True, team_id=missing_team_id)
        actions: list[RepairAction] = []

        summary = repair_persons(
            [PersonRef(team_id=missing_team_id, person_uuid=person_uuid)],
            apply=True,
            on_action=actions.append,
            log=lambda _: None,
        )

        assert [a.outcome for a in actions] == ["skipped_team_gone"]
        assert summary.person_outcomes == {"skipped_team_gone": 1}
        get_active_fake().assert_not_called("set_person_version_floor")
        get_active_fake().assert_not_called("get_persons_by_uuids")

    def test_skips_a_person_the_primary_tombstoned_while_the_replica_still_shows_it_live(self) -> None:
        person = self._pg_person(version=3)
        self._ch_person_row(person.uuid, 103, deleted=True)
        fake = get_active_fake()
        replica_view = person_pb2.Person()
        stored = fake.stored_person(self.team.pk, str(person.uuid))
        assert stored is not None
        replica_view.CopyFrom(stored)
        tombstone_persons_in_postgres(self.team.pk, [person.uuid])

        with patch.object(
            fake, "get_persons_by_uuids", return_value=person_pb2.PersonsResponse(persons=[replica_view])
        ):
            _, actions = self._repair(person.uuid)

        assert [a.outcome for a in actions] == ["skipped_tombstoned"]
        assert self._ch_person(person.uuid)[:2] == (1, 103)


class TestWritePacer(SimpleTestCase):
    def test_idle_time_before_the_writes_buys_no_burst(self) -> None:
        clock = [0.0]
        sleeps: list[float] = []

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock[0] += seconds

        with patch("posthog.models.person.divergence.time") as time_module:
            time_module.monotonic.side_effect = lambda: clock[0]
            time_module.sleep.side_effect = sleep
            pacer = _WritePacer(max_per_second=2)
            clock[0] = 10.0
            for _ in range(3):
                pacer.before_write()

        assert sleeps == [0.5, 0.5]


class TestScanTeamRanges(SimpleTestCase):
    @parameterized.expand([("out_of_memory", ClickHouseQueryMemoryLimitExceeded), ("timeout", ClickHouseQueryTimeOut)])
    def test_a_team_that_fails_alone_is_skipped_and_every_other_team_is_scanned(
        self, _name: str, error: type[Exception]
    ) -> None:
        scanned: list[int] = []

        def query(_sql: str, args: dict[str, Any], **_kwargs: Any) -> list[Any]:
            teams = range(args["min_team_id"], args["max_team_id"])
            if 7 in teams:
                raise error()
            scanned.extend(teams)
            return []

        with patch("posthog.models.person.divergence.sync_execute", side_effect=query):
            summary = scan_stale_persons(
                window_days=60, min_team_id=0, max_team_id=16, team_step=8, on_found=lambda _: None, log=lambda _: None
            )

        assert summary.skipped_team_ids == [7]
        assert sorted(scanned) == [team for team in range(16) if team != 7]
