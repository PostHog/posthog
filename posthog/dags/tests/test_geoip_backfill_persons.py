import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

import dagster

from posthog.clickhouse.cluster import ClickhouseCluster, NodeRole
from posthog.dags.geoip_backfill import GeoipStagingTable
from posthog.dags.geoip_backfill_persons import GeoipPersonsConfig, geoip_backfill_persons_job
from posthog.dags.tests.test_geoip_backfill import PUBLIC_IP, SeededEvent, run_staging, seed
from posthog.personhog_client.fake_client import fake_personhog_client


@pytest.mark.django_db
@pytest.mark.parametrize("dry_run", [False, True], ids=["repair", "dry_run"])
def test_persons_get_missing_initial_geoip_once(
    cluster: ClickhouseCluster, geoip_teams: tuple[int, int], tmp_path: Path, dry_run: bool
) -> None:
    with_geoip, _ = geoip_teams
    # nosemgrep: test-datetime-now-without-freeze (every event time and the window are offsets from this one reading)
    now = datetime.now(UTC).replace(microsecond=0)
    new_person, earlier_person = uuid4(), uuid4()
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
    ]
    seed(cluster, now, events)
    staging_run_id = run_staging(cluster, now, tmp_path).dagster_run.run_id
    try:
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=with_geoip, person_id=1, uuid=str(new_person), properties={"email": "a@example.com"}
            )
            fake.add_person(
                team_id=with_geoip,
                person_id=2,
                uuid=str(earlier_person),
                properties={"$initial_geoip_country_code": "FR"},
            )

            for _ in range(2):
                geoip_backfill_persons_job.execute_in_process(
                    run_config=dagster.RunConfig(
                        ops={
                            "repair_initial_geoip_persons": GeoipPersonsConfig(
                                staging_run_id=staging_run_id, dry_run=dry_run
                            )
                        }
                    ),
                    resources={"cluster": cluster},
                    instance=dagster.DagsterInstance.ephemeral(),
                )

            new = json.loads(fake.stored_person(with_geoip, str(new_person)).properties)
            earlier = json.loads(fake.stored_person(with_geoip, str(earlier_person)).properties)
            updates = [call for call in fake.calls if call.method == "update_person_properties"]
            if dry_run:
                assert new == {"email": "a@example.com"}
                assert earlier == {"$initial_geoip_country_code": "FR"}
                assert updates == []
            else:
                assert new["email"] == "a@example.com"
                assert new["$initial_geoip_country_code"] == "US"
                assert new["$initial_geoip_city_name"] is None
                assert earlier["$initial_geoip_country_code"] == "FR"
                assert "$initial_geoip_continent_code" in earlier
                # The second run finds every key present and writes nothing.
                assert len(updates) == 2
    finally:
        cluster.map_hosts_by_role(GeoipStagingTable(id=UUID(staging_run_id)).drop, NodeRole.DATA).result()
