from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import dagster

from posthog.clickhouse.cluster import ClickhouseCluster, NodeRole, Query
from posthog.dags.geoip_backfill import IngestionWindowConfig
from posthog.dags.geoip_backfill_verify import GeoipVerifyConfig, geoip_backfill_verify_job
from posthog.dags.tests.test_geoip_backfill import PUBLIC_IP, UNKNOWN_IP, SeededEvent, run_staging, seed
from posthog.dags.tests.test_geoip_backfill_resend import drop_staging, run_resend
from posthog.models.event.sql import EVENTS_DATA_TABLE


def verify(cluster: ClickhouseCluster, staging_run_id: str, now: datetime) -> dict[str, int]:
    window = IngestionWindowConfig(
        start=(now - timedelta(minutes=60)).isoformat(), end=(now - timedelta(minutes=10)).isoformat()
    )
    result = geoip_backfill_verify_job.execute_in_process(
        run_config=dagster.RunConfig(
            ops={"plan_geoip_verify": GeoipVerifyConfig(staging_run_id=staging_run_id, windows=[window])}
        ),
        resources={"cluster": cluster},
        instance=dagster.DagsterInstance.ephemeral(),
    )
    return result.output_for_node("verify_geoip_backfill")


@pytest.mark.django_db
def test_verify_counts_the_staged_events_before_and_after_the_resend(
    cluster: ClickhouseCluster, geoip_teams: tuple[int, int], tmp_path: Path
) -> None:
    with_geoip, _ = geoip_teams
    # nosemgrep: test-datetime-now-without-freeze (every event time and the window are offsets from this one reading)
    now = datetime.now(UTC).replace(microsecond=0)
    events = [
        SeededEvent(
            label=f"verify_{label}",
            team_id=with_geoip,
            properties={"$ip": ip},
            written_minutes_ago=30,
            person_properties={},
        )
        for label, ip in [("damaged", PUBLIC_IP), ("deleted", PUBLIC_IP), ("unknown_address", UNKNOWN_IP)]
    ]
    deleted = events[1]
    seed(cluster, now, events)
    staging_run_id = run_staging(cluster, now, tmp_path).dagster_run.run_id
    try:
        before = verify(cluster, staging_run_id, now)

        cluster.map_hosts_by_role(
            Query(f"DELETE FROM {EVENTS_DATA_TABLE()} WHERE uuid = %(uuid)s", {"uuid": deleted.uuid}),
            NodeRole.DATA,
        ).result()
        run_resend(cluster, staging_run_id, dry_run=False)
        after = verify(cluster, staging_run_id, now)

        assert before == {
            "staged": 2,
            "repaired": 0,
            "pending": 2,
            "missing": 0,
            "duplicate_rows": 0,
            "left_in_windows": 3,
        }
        # The original of the damaged event stays next to its staged copy until a merge collapses them.
        assert after == {
            "staged": 2,
            "repaired": 1,
            "pending": 0,
            "missing": 1,
            "duplicate_rows": 1,
            "left_in_windows": 1,
        }
    finally:
        drop_staging(cluster, staging_run_id)
