import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

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
from posthog.dags.tests.test_geoip_backfill import PUBLIC_IP, SeededEvent, run_staging, seed
from posthog.dataclasses import frozen
from posthog.personhog_client.fake_client import fake_personhog_client


def test_staged_person_events_merges_the_earliest_and_last_event_across_shards() -> None:
    person = str(uuid4())
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        (1, person, start, '{"$initial_geoip_country_code":"US"}', start, '{"$geoip_country_code":"US"}'),
        (
            1,
            person,
            start + timedelta(minutes=5),
            '{"$initial_geoip_country_code":"FR"}',
            start + timedelta(minutes=10),
            '{"$geoip_country_code":"FR"}',
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
                assert new["$initial_geoip_city_name"] is None
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
