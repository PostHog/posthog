"""Stop the personhog shadow lane and measure drift between the two write paths.

The job scales the lane's consumers to zero, waits for every in-flight write
to land (the personhog writer keeps draining its changelog backlog after the
consumers stop), then compares the legacy tables against the personhog tmp
tables in the shadow persons database and reports drift per category.

It never resets the database: after the run an operator can connect directly
and inspect the exact rows behind every reported number. A fresh validation
run starts with personhog_shadow_lane_start_job and reset_state=true.
"""

import time
from collections.abc import Callable
from contextlib import closing

import dagster
import psycopg2

from posthog.dags.common import JobOwners
from posthog.dags.personhog_shadow_lane import (
    SHADOW_CONSUMER_DEPLOYMENT,
    SHADOW_DB_URL_ENV_VAR,
    SHADOW_NAMESPACE,
    SHADOW_PROCESSOR_DEPLOYMENT,
    apps_api,
    deployment_pod_count,
    read_shadow_write_counter,
    scale_deployment,
    shadow_db_connection,
    wait_for_quiescence,
)
from posthog.dataclasses import frozen


@frozen
class DriftCategoryReport:
    category: str
    legacy_total: int
    personhog_total: int
    missing_in_personhog: int
    missing_in_legacy: int
    # Matched keys where at least one compared field differs. Field-level
    # counts overlap on a row, so this is counted separately in SQL.
    mismatched_rows: int
    field_mismatches: dict[str, int]
    samples: list[str]

    @property
    def compared_keys(self) -> int:
        return self.legacy_total + self.missing_in_legacy

    @property
    def drifted_rows(self) -> int:
        return self.missing_in_personhog + self.missing_in_legacy + self.mismatched_rows

    @property
    def drift_pct(self) -> float:
        if self.compared_keys == 0:
            return 0.0
        return 100.0 * self.drifted_rows / self.compared_keys


# Both paths see the same deletions but record them differently: the legacy
# path deletes rows, personhog tombstones them with is_deleted. Every
# comparison filters is_deleted on both sides so a tombstone against a
# deleted row does not read as drift.
#
# version differences are reported per field but excluded from
# mismatched_rows: version counts how many writes a row took, so a benign
# difference in update batching shifts it without any end-state divergence.
_PERSON_DRIFT_SQL = """
WITH legacy AS (
    SELECT team_id, uuid, properties, is_identified, created_at, version
    FROM posthog_person WHERE NOT is_deleted
), personhog AS (
    SELECT team_id, uuid, properties, is_identified, created_at, version
    FROM personhog_person_tmp WHERE NOT is_deleted
)
SELECT
    (SELECT count(*) FROM legacy) AS legacy_total,
    (SELECT count(*) FROM personhog) AS personhog_total,
    count(*) FILTER (WHERE p.uuid IS NULL) AS missing_in_personhog,
    count(*) FILTER (WHERE l.uuid IS NULL) AS missing_in_legacy,
    count(*) FILTER (WHERE l.uuid IS NOT NULL AND p.uuid IS NOT NULL
        AND l.properties IS DISTINCT FROM p.properties) AS properties,
    count(*) FILTER (WHERE l.uuid IS NOT NULL AND p.uuid IS NOT NULL
        AND l.is_identified IS DISTINCT FROM p.is_identified) AS is_identified,
    count(*) FILTER (WHERE l.uuid IS NOT NULL AND p.uuid IS NOT NULL
        AND l.created_at IS DISTINCT FROM p.created_at) AS created_at,
    count(*) FILTER (WHERE l.uuid IS NOT NULL AND p.uuid IS NOT NULL
        AND l.version IS DISTINCT FROM p.version) AS version,
    count(*) FILTER (WHERE l.uuid IS NOT NULL AND p.uuid IS NOT NULL AND (
        l.properties IS DISTINCT FROM p.properties
        OR l.is_identified IS DISTINCT FROM p.is_identified
        OR l.created_at IS DISTINCT FROM p.created_at)) AS mismatched_rows
FROM legacy l
FULL OUTER JOIN personhog p USING (team_id, uuid)
"""

_PERSON_SAMPLE_SQL = """
WITH legacy AS (
    SELECT team_id, uuid, properties, is_identified, created_at
    FROM posthog_person WHERE NOT is_deleted
), personhog AS (
    SELECT team_id, uuid, properties, is_identified, created_at
    FROM personhog_person_tmp WHERE NOT is_deleted
)
SELECT team_id, uuid,
    CASE WHEN p.uuid IS NULL THEN 'missing_in_personhog'
         WHEN l.uuid IS NULL THEN 'missing_in_legacy'
         ELSE 'field_mismatch' END AS drift
FROM legacy l
FULL OUTER JOIN personhog p USING (team_id, uuid)
WHERE p.uuid IS NULL OR l.uuid IS NULL
    OR l.properties IS DISTINCT FROM p.properties
    OR l.is_identified IS DISTINCT FROM p.is_identified
    OR l.created_at IS DISTINCT FROM p.created_at
LIMIT %(limit)s
"""

_DISTINCT_ID_DRIFT_SQL = """
WITH legacy AS (
    SELECT d.team_id, d.distinct_id, p.uuid AS person_uuid
    FROM posthog_persondistinctid d
    JOIN posthog_person p ON p.id = d.person_id AND p.team_id = d.team_id
    WHERE NOT d.is_deleted AND NOT p.is_deleted
), personhog AS (
    SELECT d.team_id, d.distinct_id, p.uuid AS person_uuid
    FROM personhog_persondistinctid_tmp d
    JOIN personhog_person_tmp p ON p.team_id = d.team_id AND p.id = d.person_id
    WHERE NOT d.is_deleted AND NOT p.is_deleted
)
SELECT
    (SELECT count(*) FROM legacy) AS legacy_total,
    (SELECT count(*) FROM personhog) AS personhog_total,
    count(*) FILTER (WHERE p.person_uuid IS NULL) AS missing_in_personhog,
    count(*) FILTER (WHERE l.person_uuid IS NULL) AS missing_in_legacy,
    count(*) FILTER (WHERE l.person_uuid IS NOT NULL AND p.person_uuid IS NOT NULL
        AND l.person_uuid <> p.person_uuid) AS mismatched_rows
FROM legacy l
FULL OUTER JOIN personhog p USING (team_id, distinct_id)
"""

_DISTINCT_ID_SAMPLE_SQL = """
WITH legacy AS (
    SELECT d.team_id, d.distinct_id, p.uuid AS person_uuid
    FROM posthog_persondistinctid d
    JOIN posthog_person p ON p.id = d.person_id AND p.team_id = d.team_id
    WHERE NOT d.is_deleted AND NOT p.is_deleted
), personhog AS (
    SELECT d.team_id, d.distinct_id, p.uuid AS person_uuid
    FROM personhog_persondistinctid_tmp d
    JOIN personhog_person_tmp p ON p.team_id = d.team_id AND p.id = d.person_id
    WHERE NOT d.is_deleted AND NOT p.is_deleted
)
SELECT team_id, distinct_id, l.person_uuid AS legacy_person, p.person_uuid AS personhog_person,
    CASE WHEN p.person_uuid IS NULL THEN 'missing_in_personhog'
         WHEN l.person_uuid IS NULL THEN 'missing_in_legacy'
         ELSE 'person_mismatch' END AS drift
FROM legacy l
FULL OUTER JOIN personhog p USING (team_id, distinct_id)
WHERE p.person_uuid IS NULL OR l.person_uuid IS NULL OR l.person_uuid <> p.person_uuid
LIMIT %(limit)s
"""

_HASH_KEY_DRIFT_SQL = """
WITH legacy AS (
    SELECT h.team_id, p.uuid AS person_uuid, h.feature_flag_key, h.hash_key
    FROM posthog_featureflaghashkeyoverride h
    JOIN posthog_person p ON p.id = h.person_id AND p.team_id = h.team_id
    WHERE NOT p.is_deleted
), personhog AS (
    SELECT h.team_id, p.uuid AS person_uuid, h.feature_flag_key, h.hash_key
    FROM personhog_featureflaghashkeyoverride_tmp h
    JOIN personhog_person_tmp p ON p.team_id = h.team_id AND p.id = h.person_id
    WHERE NOT p.is_deleted
)
SELECT
    (SELECT count(*) FROM legacy) AS legacy_total,
    (SELECT count(*) FROM personhog) AS personhog_total,
    count(*) FILTER (WHERE p.hash_key IS NULL) AS missing_in_personhog,
    count(*) FILTER (WHERE l.hash_key IS NULL) AS missing_in_legacy,
    count(*) FILTER (WHERE l.hash_key IS NOT NULL AND p.hash_key IS NOT NULL
        AND l.hash_key <> p.hash_key) AS mismatched_rows
FROM legacy l
FULL OUTER JOIN personhog p USING (team_id, person_uuid, feature_flag_key)
"""

_HASH_KEY_SAMPLE_SQL = """
WITH legacy AS (
    SELECT h.team_id, p.uuid AS person_uuid, h.feature_flag_key, h.hash_key
    FROM posthog_featureflaghashkeyoverride h
    JOIN posthog_person p ON p.id = h.person_id AND p.team_id = h.team_id
    WHERE NOT p.is_deleted
), personhog AS (
    SELECT h.team_id, p.uuid AS person_uuid, h.feature_flag_key, h.hash_key
    FROM personhog_featureflaghashkeyoverride_tmp h
    JOIN personhog_person_tmp p ON p.team_id = h.team_id AND p.id = h.person_id
    WHERE NOT p.is_deleted
)
SELECT team_id, person_uuid, feature_flag_key,
    CASE WHEN p.hash_key IS NULL THEN 'missing_in_personhog'
         WHEN l.hash_key IS NULL THEN 'missing_in_legacy'
         ELSE 'hash_key_mismatch' END AS drift
FROM legacy l
FULL OUTER JOIN personhog p USING (team_id, person_uuid, feature_flag_key)
WHERE p.hash_key IS NULL OR l.hash_key IS NULL OR l.hash_key <> p.hash_key
LIMIT %(limit)s
"""


def _person_samples(row: dict) -> str:
    return f"team={row['team_id']} uuid={row['uuid']} {row['drift']}"


def _distinct_id_samples(row: dict) -> str:
    return (
        f"team={row['team_id']} distinct_id={row['distinct_id']!r} "
        f"legacy_person={row['legacy_person']} personhog_person={row['personhog_person']} {row['drift']}"
    )


def _hash_key_samples(row: dict) -> str:
    return f"team={row['team_id']} person={row['person_uuid']} flag={row['feature_flag_key']} {row['drift']}"


def _run_category(
    cursor: psycopg2.extensions.cursor,
    category: str,
    drift_sql: str,
    sample_sql: str,
    format_sample: Callable[[dict], str],
    sample_size: int,
) -> DriftCategoryReport:
    cursor.execute(drift_sql)
    row = cursor.fetchone()
    field_mismatches = {
        key: int(value)
        for key, value in row.items()
        if key
        not in ("legacy_total", "personhog_total", "missing_in_personhog", "missing_in_legacy", "mismatched_rows")
    }
    samples: list[str] = []
    if sample_size > 0:
        cursor.execute(sample_sql, {"limit": sample_size})
        samples = [format_sample(sample) for sample in cursor.fetchall()]
    return DriftCategoryReport(
        category=category,
        legacy_total=int(row["legacy_total"]),
        personhog_total=int(row["personhog_total"]),
        missing_in_personhog=int(row["missing_in_personhog"]),
        missing_in_legacy=int(row["missing_in_legacy"]),
        mismatched_rows=int(row["mismatched_rows"]),
        field_mismatches=field_mismatches,
        samples=samples,
    )


def compute_shadow_drift(connection: psycopg2.extensions.connection, sample_size: int) -> list[DriftCategoryReport]:
    with connection.cursor() as cursor:
        cursor.execute("SET application_name = 'dagster_personhog_shadow_drift'")
        cursor.execute("SET statement_timeout = '30min'")
        cursor.execute("SET work_mem = '512MB'")
        return [
            _run_category(cursor, "persons", _PERSON_DRIFT_SQL, _PERSON_SAMPLE_SQL, _person_samples, sample_size),
            _run_category(
                cursor,
                "distinct_ids",
                _DISTINCT_ID_DRIFT_SQL,
                _DISTINCT_ID_SAMPLE_SQL,
                _distinct_id_samples,
                sample_size,
            ),
            _run_category(
                cursor,
                "hash_key_overrides",
                _HASH_KEY_DRIFT_SQL,
                _HASH_KEY_SAMPLE_SQL,
                _hash_key_samples,
                sample_size,
            ),
        ]


class ShadowLaneStopConfig(dagster.Config):
    namespace: str = SHADOW_NAMESPACE
    consumer_deployment: str = SHADOW_CONSUMER_DEPLOYMENT
    processor_deployment: str = SHADOW_PROCESSOR_DEPLOYMENT
    stop_timeout_seconds: int = 600


class ShadowSettleConfig(dagster.Config):
    shadow_db_env_var: str = SHADOW_DB_URL_ENV_VAR
    poll_seconds: int = 30
    stable_checks: int = 4
    timeout_seconds: int = 3600


class ShadowDriftConfig(dagster.Config):
    shadow_db_env_var: str = SHADOW_DB_URL_ENV_VAR
    sample_size: int = 10


@dagster.op
def stop_shadow_lane(context: dagster.OpExecutionContext, config: ShadowLaneStopConfig) -> None:
    apps = apps_api()
    deployments = [config.consumer_deployment, config.processor_deployment]
    for deployment in deployments:
        context.log.info(f"Scaling {config.namespace}/{deployment} to 0 replicas")
        scale_deployment(apps, config.namespace, deployment, 0)

    deadline = time.monotonic() + config.stop_timeout_seconds
    pending = set(deployments)
    while pending and time.monotonic() < deadline:
        for deployment in list(pending):
            if deployment_pod_count(apps, config.namespace, deployment) == 0:
                context.log.info(f"{deployment} has no pods left")
                pending.discard(deployment)
        if pending:
            time.sleep(10)

    if pending:
        raise dagster.Failure(
            description=f"Pods still running after {config.stop_timeout_seconds}s: {', '.join(sorted(pending))}"
        )


@dagster.op(ins={"lane_stopped": dagster.In(dagster.Nothing)})
def wait_for_shadow_settle(context: dagster.OpExecutionContext, config: ShadowSettleConfig) -> None:
    """Wait until nothing writes to the shadow persons database any more.

    The consumers are down, but the personhog writer keeps applying its
    changelog backlog. A quiet database cannot be told apart from a stalled
    writer here: if the writer crashed with backlog uncommitted, the counter
    also holds still, and the report then counts the unapplied writes as
    missing_in_personhog drift. Check the writer's health before trusting an
    unexpectedly large number there.
    """
    with closing(shadow_db_connection(config.shadow_db_env_var)) as connection:
        connection.autocommit = True

        started = time.monotonic()
        try:
            polls = wait_for_quiescence(
                lambda: read_shadow_write_counter(connection),
                poll_seconds=config.poll_seconds,
                stable_checks=config.stable_checks,
                timeout_seconds=config.timeout_seconds,
                on_progress=context.log.info,
            )
        except TimeoutError as timeout:
            raise dagster.Failure(
                description=(
                    f"The shadow persons database is still receiving writes after {config.timeout_seconds}s. "
                    "The personhog writer may still be draining a large backlog, or something outside the lane "
                    "is writing to this database. The consumers stay down; re-run this job to keep waiting."
                )
            ) from timeout

    waited = time.monotonic() - started
    context.log.info(f"Shadow persons database settled after {waited:.0f}s ({polls} polls)")
    context.add_output_metadata({"settle_seconds": dagster.MetadataValue.float(round(waited, 1))})


@dagster.op(ins={"settled": dagster.In(dagster.Nothing)})
def report_shadow_drift(context: dagster.OpExecutionContext, config: ShadowDriftConfig) -> dict:
    with closing(shadow_db_connection(config.shadow_db_env_var)) as connection:
        reports = compute_shadow_drift(connection, config.sample_size)

    header = "| category | legacy | personhog | missing in personhog | missing in legacy | mismatched | drift % |"
    separator = "|---|---|---|---|---|---|---|"
    lines = [header, separator]
    metadata: dict[str, dagster.MetadataValue] = {}
    for report in reports:
        lines.append(
            f"| {report.category} | {report.legacy_total} | {report.personhog_total} "
            f"| {report.missing_in_personhog} | {report.missing_in_legacy} "
            f"| {report.mismatched_rows} | {report.drift_pct:.4f} |"
        )
        metadata[f"{report.category}_drift_pct"] = dagster.MetadataValue.float(round(report.drift_pct, 4))
        context.log.info(
            f"[{report.category}] legacy={report.legacy_total} personhog={report.personhog_total} "
            f"missing_in_personhog={report.missing_in_personhog} missing_in_legacy={report.missing_in_legacy} "
            f"mismatched_rows={report.mismatched_rows} drift={report.drift_pct:.4f}% "
            f"field_mismatches={report.field_mismatches}"
        )
        for sample in report.samples:
            context.log.info(f"[{report.category}] drift sample: {sample}")

    metadata["summary"] = dagster.MetadataValue.md("\n".join(lines))
    context.add_output_metadata(metadata)

    return {
        report.category: {
            "legacy_total": report.legacy_total,
            "personhog_total": report.personhog_total,
            "missing_in_personhog": report.missing_in_personhog,
            "missing_in_legacy": report.missing_in_legacy,
            "mismatched_rows": report.mismatched_rows,
            "field_mismatches": report.field_mismatches,
            "drift_pct": report.drift_pct,
        }
        for report in reports
    }


@dagster.job(tags={"owner": JobOwners.TEAM_INGESTION.value})
def personhog_shadow_lane_stop_and_compare_job():
    """Stop the shadow lane, wait for writes to drain, and report drift between the two paths.

    Leaves the shadow persons database untouched so the drift behind the
    report can be inspected over a direct connection afterwards.
    """
    report_shadow_drift(wait_for_shadow_settle(stop_shadow_lane()))
