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
from posthog.models import Team
from posthog.models.person import Person
from posthog.models.person.divergence import (
    DivergentPerson,
    MappingDivergenceKind,
    PersonDivergenceKind,
    PersonRef,
    RepairAction,
    RepairOutcome,
    RepairSummary,
    SampleBucket,
    SampledPerson,
    SampleSummary,
    ScanSummary,
    TeamCheck,
    _WritePacer,
    check_team,
    repair_persons,
    scan_hidden_persons,
    scan_sample,
    scan_stale_persons,
    scan_swept_persons,
)
from posthog.models.person.sql import BULK_INSERT_PERSON_DISTINCT_ID2
from posthog.models.person.util import (
    create_person as create_person_in_ch,
    tombstone_persons_in_postgres,
)
from posthog.models.signals import mute_selected_signals
from posthog.personhog_client.fake_client import get_active_fake
from posthog.personhog_client.proto import CONSISTENCY_LEVEL_STRONG
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

    def _ch_mapping_row(
        self, distinct_id: str, person_uuid: UUID | str, version: int, *, deleted: bool = False, hours_ago: float = 0
    ) -> None:
        sync_execute(
            BULK_INSERT_PERSON_DISTINCT_ID2,
            [
                {
                    "distinct_id": distinct_id,
                    "person_id": str(person_uuid),
                    "team_id": self.team.pk,
                    "is_deleted": int(deleted),
                    "version": version,
                    "_timestamp": _utc_naive(hours_ago),
                    "_offset": 0,
                    "_partition": 0,
                }
            ],
            flush=False,
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

    def _ch_mapping(self, distinct_id: str) -> tuple[str, int, int]:
        [[person_uuid, deleted, version]] = sync_execute(
            """
            SELECT toString(argMax(person_id, version)), argMax(is_deleted, version), max(version)
            FROM person_distinct_id2 WHERE team_id = %(team_id)s AND distinct_id = %(distinct_id)s
            """,
            {"team_id": self.team.pk, "distinct_id": distinct_id},
        )
        return person_uuid, int(deleted), int(version)

    def _pg_version(self, person: Person) -> int:
        stored = get_active_fake().stored_person(self.team.pk, str(person.uuid))
        assert stored is not None
        return stored.version

    def _pg_mapping_versions(self, person: Person) -> dict[str, int]:
        response = get_active_fake().get_distinct_ids_for_persons(
            person_pb2.GetDistinctIdsForPersonsRequest(team_id=self.team.pk, person_ids=[person.pk])
        )
        return {d.distinct_id: d.version for pd in response.person_distinct_ids for d in pd.distinct_ids}

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
        distinct_id: str | None = None,
        kind: PersonDivergenceKind | MappingDivergenceKind | None = None,
        pg_version: int | None = None,
        ch_max_version: int | None = None,
        target_version: int | None = None,
    ) -> RepairAction:
        return RepairAction(
            team_id=self.team.pk,
            person_uuid=str(person_uuid),
            distinct_id=distinct_id,
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

    def test_sample_classifies_live_clickhouse_persons_against_postgres(self) -> None:
        gone_team = Team.objects.create(organization=self.organization, name="deleted team")
        gone_team_id = gone_team.pk
        gone_team.delete()
        equal = self._pg_person(version=3)
        self._ch_person_row(equal.uuid, 3, hours_ago=48)
        below = self._pg_person(version=3)
        self._ch_person_row(below.uuid, 5)
        above = self._pg_person(version=6)
        self._ch_person_row(above.uuid, 5)
        tombstoned = self._pg_person(version=3)
        tombstone_persons_in_postgres(self.team.pk, [tombstoned.uuid])
        self._ch_person_row(tombstoned.uuid, 3)
        absent = uuid4()
        self._ch_person_row(absent, 3)
        team_gone = uuid4()
        self._ch_person_row(team_gone, 1, team_id=gone_team_id)
        # Postgres can still hold a deleted team's persons until the team purge reaches them.
        team_gone_in_postgres = uuid4()
        self._ch_person_row(team_gone_in_postgres, 1, team_id=gone_team_id)
        get_active_fake().add_person(team_id=gone_team_id, person_id=987655, uuid=str(team_gone_in_postgres), version=1)
        deleted_winner = self._pg_person(version=3)
        self._ch_person_row(deleted_winner.uuid, 4, deleted=True)
        written_long_ago = self._pg_person(version=3)
        self._ch_person_row(written_long_ago.uuid, 3, hours_ago=24 * 10)

        sampled: list[SampledPerson] = []
        summary = scan_sample(
            modulus=1,
            residue=0,
            written_within_days=5,
            cutoff=now() - timedelta(days=1),
            min_team_id=self.team.pk,
            max_team_id=gone_team_id + 1,
            team_step=1,
            on_sampled=sampled.append,
            log=lambda _: None,
        )

        assert {s.person_uuid: (s.classification, s.era, s.pg_version) for s in sampled} == {
            str(equal.uuid): ("equal", "before_cutoff", 3),
            str(below.uuid): ("pg_below_ch", "since_cutoff", 3),
            str(above.uuid): ("pg_above_ch", "since_cutoff", 6),
            str(tombstoned.uuid): ("pg_tombstone", "since_cutoff", None),
            str(absent): ("pg_absent", "since_cutoff", None),
            str(team_gone): ("team_gone", "since_cutoff", None),
            str(team_gone_in_postgres): ("team_gone", "since_cutoff", None),
        }
        assert summary.sampled == 7
        assert summary.skipped_team_ids == []
        assert all(
            call.request.team_id != gone_team_id
            for call in get_active_fake().calls
            if call.method == "get_persons_by_uuids"
        )
        assert summary.counts[SampleBucket(classification="equal", era="before_cutoff")] == 1

    def test_team_check_counts_old_live_clickhouse_rows_that_postgres_still_holds(self) -> None:
        kept = self._pg_person(version=1, distinct_ids={"kept": 0})
        self._ch_person_row(kept.uuid, 1, hours_ago=48)
        self._ch_mapping_row("kept", kept.uuid, 0, hours_ago=48)
        lost = uuid4()
        self._ch_person_row(lost, 1, hours_ago=48)
        self._ch_mapping_row("lost", lost, 0, hours_ago=48)
        recent = self._pg_person(version=1, distinct_ids={"recent": 0})
        self._ch_person_row(recent.uuid, 1)
        self._ch_mapping_row("recent", recent.uuid, 0)
        deleted = uuid4()
        self._ch_person_row(deleted, 1, deleted=True, hours_ago=48)
        self._ch_mapping_row("deleted", deleted, 1, deleted=True, hours_ago=48)

        result = check_team(team_id=self.team.pk, sample_size=10, before=now() - timedelta(days=1))

        assert result == TeamCheck(
            team_id=self.team.pk,
            persons_sampled=2,
            persons_live_in_postgres=1,
            distinct_ids_sampled=2,
            distinct_ids_live_in_postgres=1,
        )

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
    def test_repairs_a_hidden_person_and_its_hidden_mapping_only_when_applied(self, _name: str, apply: bool) -> None:
        person = self._pg_person(version=3, distinct_ids={"hidden-did": 0})
        self._ch_person_row(person.uuid, 3)
        self._ch_person_row(person.uuid, 103, deleted=True)
        self._ch_mapping_row("hidden-did", person.uuid, 0)
        self._ch_mapping_row("hidden-did", person.uuid, 100, deleted=True)

        summary, actions = self._repair(person.uuid, apply=apply)

        outcome: RepairOutcome = "repaired" if apply else "would_repair"
        assert actions == [
            self._action(person.uuid, outcome, kind="hidden", pg_version=3, ch_max_version=103, target_version=104),
            self._action(
                person.uuid,
                outcome,
                distinct_id="hidden-did",
                kind="hidden",
                pg_version=0,
                ch_max_version=100,
                target_version=101,
            ),
        ]
        assert summary.applied is apply
        if apply:
            assert (self._pg_version(person), self._pg_mapping_versions(person)) == (104, {"hidden-did": 101})
            assert self._ch_person(person.uuid) == (0, 104, PG_PROPERTIES)
            assert self._ch_mapping("hidden-did") == (str(person.uuid), 0, 101)
        else:
            get_active_fake().assert_not_called("set_person_version_floor")
            get_active_fake().assert_not_called("set_person_distinct_id_version_floor")
            assert (self._pg_version(person), self._pg_mapping_versions(person)) == (3, {"hidden-did": 0})
            assert self._ch_person(person.uuid) == (1, 103, CH_PROPERTIES)
            assert self._ch_mapping("hidden-did") == (str(person.uuid), 1, 100)

    @parameterized.expand([("dry_run", False, []), ("apply", True, [1.0])])
    def test_throttles_on_each_divergent_row_written(self, _name: str, apply: bool, sleeps: list[float]) -> None:
        person = self._pg_person(version=3, distinct_ids={"throttled-did": 0})
        self._ch_person_row(person.uuid, 103, deleted=True)
        self._ch_mapping_row("throttled-did", person.uuid, 100, deleted=True)

        with patch("posthog.models.person.divergence.time") as clock:
            clock.monotonic.return_value = 0.0
            repair_persons(
                [PersonRef(team_id=self.team.pk, person_uuid=str(person.uuid))],
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
            person = self._pg_person(version=3, distinct_ids={"steady": 2})
            self._ch_person_row(person.uuid, 3)
            self._ch_mapping_row("steady", person.uuid, 1)
            return person.uuid
        if case == "tombstoned_in_postgres":
            person = self._pg_person(version=3)
            tombstone_persons_in_postgres(self.team.pk, [person.uuid])
            self._ch_person_row(person.uuid, 103, deleted=True)
            return person.uuid
        if case == "stale_without_include_stale":
            person = self._pg_person(version=5, distinct_ids={"stale-did": 2})
            self._ch_person_row(person.uuid, 10)
            self._ch_person_row(person.uuid, 5)
            self._ch_mapping_row("stale-did", person.uuid, 100, deleted=True)
            return person.uuid
        absent = uuid4()
        self._ch_person_row(absent, 103, deleted=True)
        return absent

    @parameterized.expand(
        [
            ("in_sync", ["skipped_not_divergent", "skipped_not_divergent"]),
            ("tombstoned_in_postgres", ["skipped_not_live"]),
            ("absent_from_postgres", ["skipped_not_live"]),
            ("stale_without_include_stale", ["skipped_stale", "skipped_stale"]),
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
        get_active_fake().assert_not_called("set_person_distinct_id_version_floor")
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
        person = self._pg_person(version=3, distinct_ids={"lagging-did": 0})
        self._ch_person_row(person.uuid, 103, deleted=True)
        self._ch_mapping_row("lagging-did", person.uuid, 100, deleted=True)
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

        assert [(a.distinct_id, a.outcome) for a in actions] == [
            (None, "skipped_tombstoned"),
            ("lagging-did", "skipped_tombstoned"),
        ]
        assert self._ch_person(person.uuid)[:2] == (1, 103)
        assert self._ch_mapping("lagging-did") == (str(person.uuid), 1, 100)

    @parameterized.expand(
        [
            ("winner_deleted", "self", True, 100, "hidden", 101),
            ("winner_is_another_person", "other", False, 7, "other_person", 8),
            ("winner_is_another_person_below_postgres", "other", False, 1, "other_person", 2),
            ("winner_above_postgres", "self", False, 7, "stale", 8),
            ("absent_from_clickhouse", None, False, None, "absent", 2),
        ]
    )
    def test_republishes_a_divergent_mapping_for_its_postgres_owner(
        self,
        _name: str,
        ch_owner: str | None,
        ch_deleted: bool,
        ch_version: int | None,
        kind: MappingDivergenceKind,
        target_version: int,
    ) -> None:
        person = self._pg_person(version=3, distinct_ids={"divergent": 2, "steady": 0})
        self._ch_person_row(person.uuid, 3)
        self._ch_mapping_row("steady", person.uuid, 0)
        if ch_owner is not None and ch_version is not None:
            owner = person.uuid if ch_owner == "self" else uuid4()
            self._ch_mapping_row("divergent", owner, ch_version, deleted=ch_deleted)

        _, actions = self._repair(person.uuid)

        assert actions == [
            self._action(person.uuid, "skipped_not_divergent", pg_version=3, ch_max_version=3),
            self._action(person.uuid, "skipped_not_divergent", distinct_id="steady", pg_version=0, ch_max_version=0),
            self._action(
                person.uuid,
                "repaired",
                distinct_id="divergent",
                kind=kind,
                pg_version=2,
                ch_max_version=ch_version,
                target_version=target_version,
            ),
        ]
        floors = get_active_fake().assert_called("set_person_distinct_id_version_floor", times=1)
        assert floors[0].request.distinct_id == "divergent"
        get_active_fake().assert_not_called("set_person_version_floor")
        assert self._pg_mapping_versions(person)["divergent"] == target_version
        assert self._ch_mapping("divergent") == (str(person.uuid), 0, target_version)

    @parameterized.expand(
        [
            # A personhog-replica build without NULL-version handling leaves the stored version unchanged.
            ("floor_not_applied", None, "skipped_reread_lagging", 2, (1, 100)),
            # A concurrent write took the mapping past the target, so the publish carries the stored version.
            ("stored_past_the_target", 5, "repaired", 106, (0, 106)),
        ]
    )
    def test_publishes_a_mapping_only_at_the_version_the_primary_holds(
        self,
        _name: str,
        extra_versions: int | None,
        outcome: RepairOutcome,
        stored_version: int,
        ch_deleted_and_version: tuple[int, int],
    ) -> None:
        person = self._pg_person(version=3, distinct_ids={"divergent": 2})
        self._ch_person_row(person.uuid, 3)
        self._ch_mapping_row("divergent", person.uuid, 100, deleted=True)
        fake = get_active_fake()
        raise_floor = fake.set_person_distinct_id_version_floor

        def raise_floor_differently(
            request: person_pb2.SetPersonDistinctIdVersionFloorRequest, timeout: float | None = None
        ) -> person_pb2.SetPersonDistinctIdVersionFloorResponse:
            min_version = 0 if extra_versions is None else request.min_version + extra_versions
            return raise_floor(
                person_pb2.SetPersonDistinctIdVersionFloorRequest(
                    team_id=request.team_id, distinct_id=request.distinct_id, min_version=min_version
                ),
                timeout,
            )

        with patch.object(fake, "set_person_distinct_id_version_floor", side_effect=raise_floor_differently):
            _, actions = self._repair(person.uuid)

        assert [(a.distinct_id, a.outcome, a.target_version) for a in actions] == [
            (None, "skipped_not_divergent", None),
            ("divergent", outcome, 101),
        ]
        assert self._pg_mapping_versions(person)["divergent"] == stored_version
        assert self._ch_mapping("divergent") == (str(person.uuid), *ch_deleted_and_version)

    def test_repairs_the_person_but_reports_its_mappings_when_it_has_too_many_distinct_ids(self) -> None:
        person = self._pg_person(version=3, distinct_ids={"a": 0, "b": 0, "c": 0})
        self._ch_person_row(person.uuid, 103, deleted=True)
        self._ch_mapping_row("a", person.uuid, 100, deleted=True)

        with patch("posthog.models.person.divergence._MAX_REPAIR_DISTINCT_IDS_PER_PERSON", 2):
            summary, actions = self._repair(person.uuid)

        assert actions == [
            self._action(person.uuid, "repaired", kind="hidden", pg_version=3, ch_max_version=103, target_version=104),
            self._action(person.uuid, "skipped_too_many_distinct_ids"),
        ]
        assert (summary.person_outcomes, summary.mapping_outcomes) == (
            {"repaired": 1},
            {"skipped_too_many_distinct_ids": 1},
        )
        reads = get_active_fake().assert_called("get_distinct_ids_for_persons", times=1)
        assert reads[0].request.limit_per_person == 3
        get_active_fake().assert_not_called("set_person_distinct_id_version_floor")
        assert self._ch_person(person.uuid) == (0, 104, PG_PROPERTIES)
        assert self._ch_mapping("a") == (str(person.uuid), 1, 100)

    def test_leaves_a_mapping_unpublished_once_the_primary_moved_it_to_another_person(self) -> None:
        person = self._pg_person(version=3, distinct_ids={"moved": 0})
        self._ch_person_row(person.uuid, 3)
        self._ch_mapping_row("moved", person.uuid, 100, deleted=True)
        new_owner = self._pg_person(version=1)
        # The primary maps the id to new_owner while the replica list read for person still carries it.
        with mute_selected_signals():
            add_distinct_id(person=new_owner, distinct_id="moved")

        _, actions = self._repair(person.uuid)

        assert [(a.distinct_id, a.outcome) for a in actions] == [
            (None, "skipped_not_divergent"),
            ("moved", "skipped_owner_changed"),
        ]
        assert self._ch_mapping("moved") == (str(person.uuid), 1, 100)

    def test_leaves_a_mapping_unpublished_once_the_primary_no_longer_lists_it_after_the_raise(self) -> None:
        person = self._pg_person(version=3, distinct_ids={"gone": 0})
        self._ch_person_row(person.uuid, 3)
        self._ch_mapping_row("gone", person.uuid, 100, deleted=True)
        fake = get_active_fake()
        list_distinct_ids = fake.get_distinct_ids_for_persons

        def primary_lost_the_mapping(
            request: person_pb2.GetDistinctIdsForPersonsRequest,
        ) -> person_pb2.GetDistinctIdsForPersonsResponse:
            if request.read_options.consistency == CONSISTENCY_LEVEL_STRONG:
                return person_pb2.GetDistinctIdsForPersonsResponse()
            return list_distinct_ids(request)

        with patch.object(fake, "get_distinct_ids_for_persons", side_effect=primary_lost_the_mapping):
            _, actions = self._repair(person.uuid)

        assert [(a.distinct_id, a.outcome) for a in actions] == [
            (None, "skipped_not_divergent"),
            ("gone", "skipped_mapping_gone"),
        ]
        assert self._ch_mapping("gone") == (str(person.uuid), 1, 100)


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
    @parameterized.expand(
        [
            (f"{scan}_{name}", scan, error)
            for scan in ("stale", "sample")
            for name, error in (
                ("out_of_memory", ClickHouseQueryMemoryLimitExceeded),
                ("timeout", ClickHouseQueryTimeOut),
            )
        ]
    )
    def test_a_team_that_fails_alone_is_skipped_and_every_other_team_is_scanned(
        self, _name: str, scan: str, error: type[Exception]
    ) -> None:
        scanned: list[int] = []

        def query(_sql: str, args: dict[str, Any], **_kwargs: Any) -> list[Any]:
            teams = range(args["min_team_id"], args["max_team_id"])
            if 7 in teams:
                raise error()
            scanned.extend(teams)
            return []

        with patch("posthog.models.person.divergence.sync_execute", side_effect=query):
            if scan == "stale":
                summary: ScanSummary | SampleSummary = scan_stale_persons(
                    window_days=60,
                    min_team_id=0,
                    max_team_id=16,
                    team_step=8,
                    on_found=lambda _: None,
                    log=lambda _: None,
                )
            else:
                summary = scan_sample(
                    modulus=1,
                    residue=0,
                    min_team_id=0,
                    max_team_id=16,
                    team_step=8,
                    on_sampled=lambda _: None,
                    log=lambda _: None,
                )

        assert summary.skipped_team_ids == [7]
        assert sorted(scanned) == [team for team in range(16) if team != 7]
