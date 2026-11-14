import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from unittest.mock import patch

import grpc
import dagster

from posthog.clickhouse.cluster import ClickhouseCluster, NodeRole, Query
from posthog.dags.geoip_backfill import GeoipStagingTable
from posthog.dags.geoip_backfill_persons import (
    INITIAL_GEOIP_KEYS,
    GeoipPersonsConfig,
    GeoipPersonsLog,
    StagedPersonEvents,
    geoip_backfill_persons_job,
    staged_person_events,
)
from posthog.dags.tests.conftest import GeoipTeams
from posthog.dags.tests.test_geoip_backfill import (
    PUBLIC_IP,
    SeededEvent,
    output_metadata,
    run_staging,
    seed,
    staged_rows,
)
from posthog.dataclasses import frozen
from posthog.personhog_client.fake_client import FakePersonHogClient, fake_personhog_client


def test_staged_person_events_merges_the_earliest_and_last_event_across_shards() -> None:
    person = str(uuid4())
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        (1, person, start, '{"$initial_geoip_country_code":"US"}', start, '{"$geoip_country_code":"US"}', "a"),
        (
            1,
            person,
            start + timedelta(minutes=5),
            '{"$initial_geoip_country_code":"FR"}',
            start + timedelta(minutes=10),
            '{"$geoip_country_code":"FR"}',
            "b",
        ),
    ]

    [merged] = staged_person_events([StagedPersonEvents.from_row(row) for row in rows]).values()

    assert merged.initial_geoip["$initial_geoip_country_code"] == "US"
    assert merged.latest_geoip["$geoip_country_code"] == "FR"
    assert merged.last_written_at == start + timedelta(minutes=10)


@frozen
class WrittenPerson:
    set_once: dict[str, Any]
    set_properties: dict[str, Any]
    previous: dict[str, Any]


def written_persons(cluster: ClickhouseCluster, run_id: str) -> dict[int, WrittenPerson]:
    rows = cluster.any_host_by_role(
        Query(
            f"""SELECT person_id, set_once_properties, set_properties, previous_properties
            FROM {GeoipPersonsLog(id=UUID(run_id)).qualified_name}"""
        ),
        NodeRole.DATA,
    ).result()
    return {
        row[0]: WrittenPerson(
            set_once=json.loads(row[1]), set_properties=json.loads(row[2]), previous=json.loads(row[3])
        )
        for row in rows
    }


@pytest.mark.django_db
@pytest.mark.parametrize("dry_run", [False, True], ids=["repair", "dry_run"])
def test_persons_get_missing_geoip_once(
    cluster: ClickhouseCluster, geoip_teams: GeoipTeams, tmp_path: Path, dry_run: bool
) -> None:
    with_geoip = geoip_teams.with_geoip
    # nosemgrep: test-datetime-now-without-freeze (every event time and the window are offsets from this one reading)
    now = datetime.now(UTC).replace(microsecond=0)
    new_person, earlier_person, located_later = uuid4(), uuid4(), uuid4()
    events = [
        SeededEvent(
            label=f"persons_new_{dry_run}",
            team_id=with_geoip,
            properties={"$ip": PUBLIC_IP},
            written_minutes_ago=30,
            person_properties={},
            person_uuid=new_person,
        ),
        SeededEvent(
            label=f"persons_earlier_{dry_run}",
            team_id=with_geoip,
            properties={"$ip": PUBLIC_IP},
            written_minutes_ago=30,
            person_properties={},
            person_uuid=earlier_person,
        ),
        SeededEvent(
            label=f"persons_located_later_damaged_{dry_run}",
            team_id=with_geoip,
            properties={"$ip": PUBLIC_IP},
            written_minutes_ago=30,
            person_properties={},
            person_uuid=located_later,
        ),
        SeededEvent(
            label=f"persons_located_later_{dry_run}",
            team_id=with_geoip,
            properties={"$ip": PUBLIC_IP, "$geoip_country_code": "DE", "$set": {"$geoip_country_code": "DE"}},
            written_minutes_ago=5,
            person_properties={},
            person_uuid=located_later,
        ),
    ]
    seed(cluster, now, events)
    staging_run_id = run_staging(cluster, now, tmp_path).dagster_run.run_id
    persons_run_ids: list[str] = []
    try:
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=with_geoip, person_id=1, uuid=str(new_person), properties={"email": "a@example.com"}
            )
            fake.add_person(
                team_id=with_geoip,
                person_id=2,
                uuid=str(earlier_person),
                properties={"$initial_geoip_country_code": "FR", "$geoip_country_code": "FR"},
            )
            located_later_properties = {
                **dict.fromkeys(INITIAL_GEOIP_KEYS, "DE"),
                "$geoip_country_code": "DE",
            }
            fake.add_person(
                team_id=with_geoip, person_id=3, uuid=str(located_later), properties=located_later_properties
            )

            for _ in range(2):
                result = geoip_backfill_persons_job.execute_in_process(
                    run_config=dagster.RunConfig(
                        ops={
                            "repair_geoip_persons": GeoipPersonsConfig(
                                staging_run_id=staging_run_id, dry_run=dry_run, repair_latest_geoip=True
                            )
                        }
                    ),
                    resources={"cluster": cluster},
                    instance=dagster.DagsterInstance.ephemeral(),
                )
                persons_run_ids.append(result.dagster_run.run_id)

            new = json.loads(fake.stored_person(with_geoip, str(new_person)).properties)
            earlier = json.loads(fake.stored_person(with_geoip, str(earlier_person)).properties)
            later = json.loads(fake.stored_person(with_geoip, str(located_later)).properties)
            updates = [call for call in fake.calls if call.method == "update_person_properties"]
            assert later == located_later_properties
            first_log, second_log = (written_persons(cluster, run_id) for run_id in persons_run_ids)
            assert set(first_log) == {1, 2}
            logged = first_log[2]
            assert logged.set_once["$initial_geoip_country_code"] == "US"
            assert logged.set_properties["$geoip_country_code"] == "US"
            assert logged.previous == {"$initial_geoip_country_code": "FR", "$geoip_country_code": "FR"}
            assert set(second_log) == (set() if not dry_run else {1, 2})
            if dry_run:
                assert new == {"email": "a@example.com"}
                assert earlier == {"$initial_geoip_country_code": "FR", "$geoip_country_code": "FR"}
                assert updates == []
            else:
                assert new["email"] == "a@example.com"
                assert new["$initial_geoip_country_code"] == "US"
                assert new["$initial_geoip_city_name"] == "Milton"
                assert new["$initial_geoip_subdivision_2_name"] is None
                assert new["$geoip_country_code"] == "US"
                assert earlier["$initial_geoip_country_code"] == "FR"
                assert "$initial_geoip_continent_code" in earlier
                assert earlier["$geoip_country_code"] == "US"
                # The second run finds every key present and writes nothing.
                assert len(updates) == 2
    finally:
        cluster.map_hosts_by_role(GeoipStagingTable(id=UUID(staging_run_id)).drop, NodeRole.DATA).result()
        for run_id in persons_run_ids:
            cluster.map_hosts_by_role(GeoipPersonsLog(id=UUID(run_id)).drop, NodeRole.DATA).result()


def run_persons(cluster: ClickhouseCluster, staging_run_id: str, **overrides: Any) -> dagster.ExecuteInProcessResult:
    return geoip_backfill_persons_job.execute_in_process(
        run_config=dagster.RunConfig(
            ops={"repair_geoip_persons": GeoipPersonsConfig(staging_run_id=staging_run_id, **overrides)}
        ),
        resources={"cluster": cluster},
        instance=dagster.DagsterInstance.ephemeral(),
        raise_on_error=False,
    )


def drop_tables(cluster: ClickhouseCluster, staging_run_id: str, persons_run_ids: list[str]) -> None:
    cluster.map_hosts_by_role(GeoipStagingTable(id=UUID(staging_run_id)).drop, NodeRole.DATA).result()
    for run_id in persons_run_ids:
        cluster.map_hosts_by_role(GeoipPersonsLog(id=UUID(run_id)).drop, NodeRole.DATA).result()


def stage_persons(
    cluster: ClickhouseCluster, team_id: int, tmp_path: Path, labels: list[str]
) -> tuple[str, dict[str, SeededEvent]]:
    # nosemgrep: test-datetime-now-without-freeze (every event time and the window are offsets from this one reading)
    now = datetime.now(UTC).replace(microsecond=0)
    events = {
        label: SeededEvent(
            label=f"persons_{label}",
            team_id=team_id,
            properties={"$ip": PUBLIC_IP},
            written_minutes_ago=30,
            person_properties={},
            person_uuid=uuid4(),
        )
        for label in labels
    }
    seed(cluster, now, list(events.values()))
    return run_staging(cluster, now, tmp_path).dagster_run.run_id, events


@pytest.mark.django_db
def test_persons_write_filtered_keys_and_handle_each_leader_answer(
    cluster: ClickhouseCluster, geoip_teams: GeoipTeams, tmp_path: Path
) -> None:
    team_id = geoip_teams.with_geoip
    staging_run_id, events = stage_persons(
        cluster, team_id, tmp_path, ["filtered_only", "destroyed", "oversized", "handoff", "merged", "deleted"]
    )
    staged = staged_rows(cluster, GeoipStagingTable(id=UUID(staging_run_id)))
    located = {
        **staged[events["filtered_only"].uuid].properties["$set_once"],
        **staged[events["filtered_only"].uuid].properties["$set"],
    }
    persons_run_ids: list[str] = []
    try:
        with fake_personhog_client() as fake:
            # Holds every key the staged event sets, with only a filtered key out of date.
            fake.add_person(
                team_id=team_id,
                person_id=1,
                uuid=str(events["filtered_only"].person_uuid),
                properties={**located, "$geoip_latitude": 0.0},
            )
            for person_id, label in enumerate(["destroyed", "oversized", "handoff"], start=2):
                fake.add_person(team_id=team_id, person_id=person_id, uuid=str(events[label].person_uuid))
            fake.fail_updates(team_id, 2, grpc.StatusCode.NOT_FOUND)
            fake.fail_updates(team_id, 3, grpc.StatusCode.INVALID_ARGUMENT)
            fake.fail_updates(team_id, 4, grpc.StatusCode.FAILED_PRECONDITION, grpc.StatusCode.RESOURCE_EXHAUSTED)
            # The merged person's events now belong to another person, found by the event's distinct ID.
            absorber_uuid = str(uuid4())
            fake.add_person(team_id=team_id, person_id=5, uuid=absorber_uuid, distinct_ids=["user-persons_merged"])

            results = [
                run_persons(cluster, staging_run_id, dry_run=False, repair_latest_geoip=True, retry_backoff_seconds=0)
                for _ in range(2)
            ]
            persons_run_ids.extend(result.dagster_run.run_id for result in results)
            first, second = (output_metadata(result, "repair_geoip_persons") for result in results)

            assert all(result.success for result in results)
            stored = json.loads(fake.stored_person(team_id, str(events["filtered_only"].person_uuid)).properties)
            assert stored["$geoip_latitude"] == located["$geoip_latitude"]
            assert {name: first[name] for name in ("written", "skipped_not_found", "skipped_invalid", "retried")} == {
                "written": 3,
                "skipped_not_found": 1,
                "skipped_invalid": 1,
                "retried": 2,
            }
            assert (first["merged"], first["not_found"]) == (1, 1)
            absorber = json.loads(fake.stored_person(team_id, absorber_uuid).properties)
            assert absorber["$initial_geoip_country_code"] == "US"
            assert "$geoip_country_code" not in absorber
            # The forced write landed, so the second run leaves that person out. The two persons the leader
            # rejected stay in this fake, so the second run plans them again.
            assert set(written_persons(cluster, persons_run_ids[1])) == {2, 3}
            assert second["written"] == 2
    finally:
        drop_tables(cluster, staging_run_id, persons_run_ids)


@pytest.mark.django_db
def test_persons_refuse_to_write_without_the_leader_path(
    cluster: ClickhouseCluster, geoip_teams: GeoipTeams, tmp_path: Path
) -> None:
    staging_run_id, _ = stage_persons(cluster, geoip_teams.with_geoip, tmp_path, ["no_leader"])
    persons_run_ids: list[str] = []
    try:
        with fake_personhog_client() as fake:
            fake.leader_path_configured = False

            result = run_persons(cluster, staging_run_id, dry_run=False)
            persons_run_ids.append(result.dagster_run.run_id)

            assert not result.success
            assert fake.calls == []
            log = GeoipPersonsLog(id=UUID(result.dagster_run.run_id))
            [[tables]] = cluster.any_host_by_role(
                Query("SELECT count() FROM system.tables WHERE name = %(name)s", {"name": log.name}), NodeRole.DATA
            ).result()
            assert tables == 0
    finally:
        drop_tables(cluster, staging_run_id, persons_run_ids)


@pytest.mark.django_db
def test_persons_keep_a_location_set_between_the_plan_and_the_write(
    cluster: ClickhouseCluster, geoip_teams: GeoipTeams, tmp_path: Path
) -> None:
    team_id = geoip_teams.with_geoip
    staging_run_id, events = stage_persons(cluster, team_id, tmp_path, ["located_meanwhile"])
    person_uuid = str(events["located_meanwhile"].person_uuid)
    persons_run_ids: list[str] = []
    try:
        with fake_personhog_client() as fake:
            fake.add_person(team_id=team_id, person_id=1, uuid=person_uuid, properties={"email": "a@example.com"})
            reads: list[Any] = []

            def read(request: Any) -> Any:
                response = FakePersonHogClient.get_persons_by_uuids(fake, request)
                if not reads:
                    # An event that sets a location lands right after the plan read the person.
                    person = fake.stored_person(team_id, person_uuid)
                    assert person is not None
                    located = {**json.loads(person.properties), "$geoip_country_code": "DE"}
                    person.properties = json.dumps(located).encode()
                reads.append(request)
                return response

            with patch.object(fake, "get_persons_by_uuids", side_effect=read):
                result = run_persons(cluster, staging_run_id, dry_run=False, repair_latest_geoip=True)
            persons_run_ids.append(result.dagster_run.run_id)

            assert result.success
            stored = json.loads(fake.stored_person(team_id, person_uuid).properties)
            assert stored["$geoip_country_code"] == "DE"
            assert stored["$initial_geoip_country_code"] == "US"
            assert output_metadata(result, "repair_geoip_persons")["latest_changed_before_write"] == 1
    finally:
        drop_tables(cluster, staging_run_id, persons_run_ids)


@pytest.mark.django_db
def test_persons_give_a_merged_person_the_initial_geoip_of_its_earliest_staged_event(
    cluster: ClickhouseCluster, geoip_teams: GeoipTeams, tmp_path: Path
) -> None:
    team_id = geoip_teams.with_geoip
    # nosemgrep: test-datetime-now-without-freeze (every event time and the window are offsets from this one reading)
    now = datetime.now(UTC).replace(microsecond=0)
    absorber, absorbed = uuid4(), uuid4()
    seed(
        cluster,
        now,
        [
            # The test DB has only a continent for this address.
            SeededEvent(
                label="persons_absorbed",
                team_id=team_id,
                properties={"$ip": "2a02:d500::1"},
                written_minutes_ago=40,
                person_properties={},
                person_uuid=absorbed,
            ),
            SeededEvent(
                label="persons_absorber",
                team_id=team_id,
                properties={"$ip": PUBLIC_IP},
                written_minutes_ago=20,
                person_properties={},
                person_uuid=absorber,
            ),
        ],
    )
    staging_run_id = run_staging(cluster, now, tmp_path).dagster_run.run_id
    persons_run_ids: list[str] = []
    try:
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=team_id,
                person_id=1,
                uuid=str(absorber),
                properties={"email": "a@example.com"},
                distinct_ids=["user-persons_absorber", "user-persons_absorbed"],
            )

            result = run_persons(cluster, staging_run_id, dry_run=False, repair_latest_geoip=True)
            persons_run_ids.append(result.dagster_run.run_id)

            assert result.success
            stored = json.loads(fake.stored_person(team_id, str(absorber)).properties)
            assert stored["$initial_geoip_continent_code"] == "EU"
            assert stored["$initial_geoip_country_code"] is None
            assert "$geoip_continent_code" not in stored
            assert output_metadata(result, "repair_geoip_persons")["merged"] == 1
    finally:
        drop_tables(cluster, staging_run_id, persons_run_ids)
