"""Operate the personhog shadow validation lane.

The shadow lane is a second consumer group on the team 2 events topic whose
worker runs with PERSONS_STORE_MODE=shadow: every person write goes through
both the legacy direct-to-Postgres path and the personhog path, into a
dedicated persons-shadow database. Validation runs compare the two paths'
tables afterwards, so each run must start from identical (empty) state on
both sides.

This module holds the shared plumbing (Kubernetes scaling, shadow DB access,
the table inventory) and the start job. The stop/drain/compare job lives in
personhog_shadow_drift.py.

The Dagster service account needs get/patch on deployments and
deployments/scale plus list on pods in the lane namespace, and the lane's
ArgoCD Applications
must ignore Deployment spec.replicas, or ArgoCD self-heal reverts every scale
these jobs apply. Both are charts-side prerequisites.
"""

import os
import time
from contextlib import closing
from urllib.parse import urlparse

import dagster
import psycopg2
import psycopg2.extras
from kubernetes import (
    client as k8s_client,
    config as k8s_config,
)

from posthog.dags.common import JobOwners

SHADOW_NAMESPACE = "ingestion-analytics-team2-shadow"
SHADOW_CONSUMER_DEPLOYMENT = "ingestion-analytics-team2-shadow-consumer"
SHADOW_PROCESSOR_DEPLOYMENT = "ingestion-analytics-team2-shadow-processor"
SHADOW_DB_URL_ENV_VAR = "PERSONS_SHADOW_DB_URL"

# Every table the lane writes, per path. The reset truncates both lists in one
# statement so a validation run starts from state where "row missing on one
# side" can only mean drift. Kept in sync with rust/persons_migrations/.
LEGACY_STATE_TABLES = [
    "posthog_person",
    "posthog_persondistinctid",
    "posthog_personlessdistinctid",
    "posthog_featureflaghashkeyoverride",
    "posthog_personoverridemapping",
    "posthog_personoverride",
    "posthog_pendingpersonoverride",
    "posthog_flatpersonoverride",
    "posthog_group",
    "posthog_grouptypemapping",
]
PERSONHOG_STATE_TABLES = [
    "personhog_person_tmp",
    "personhog_persondistinctid_tmp",
    "personhog_featureflaghashkeyoverride_tmp",
    "lifecycle_op",
    "lifecycle_op_person",
    "lifecycle_op_tmp",
    "lifecycle_op_person_tmp",
    "person_pg_cleanup_queue",
    "person_tombstone_publish_queue",
]


def require_shadow_dsn(connection_url: str) -> None:
    """Refuse a DSN that does not look like the persons-shadow cluster.

    The reset truncates person tables. The only structural difference between
    the shadow DSN and the production persons DSN is the cluster name, so this
    guard is what stands between a misconfigured env var and truncating
    production state.
    """
    parsed = urlparse(connection_url)
    identity = f"{parsed.hostname or ''}/{parsed.path.lstrip('/')}"
    if "shadow" not in identity:
        raise dagster.Failure(
            description=(
                f"Connection target {identity!r} does not contain 'shadow'. "
                "Refusing to operate on a database that is not the persons-shadow cluster."
            )
        )


def shadow_db_connection(env_var: str) -> psycopg2.extensions.connection:
    connection_url = os.environ.get(env_var)
    if not connection_url:
        raise dagster.Failure(
            description=(
                f"Environment variable {env_var} is not set on the Dagster deployment. "
                "It must hold the persons-shadow database connection URL."
            )
        )
    require_shadow_dsn(connection_url)
    return psycopg2.connect(connection_url, cursor_factory=psycopg2.extras.RealDictCursor, connect_timeout=10)


def _load_k8s_config() -> None:
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()


def apps_api() -> k8s_client.AppsV1Api:
    _load_k8s_config()
    return k8s_client.AppsV1Api()


def deployment_pod_count(apps: k8s_client.AppsV1Api, namespace: str, name: str) -> int:
    """Count the deployment's pods straight from the pod list.

    status.replicas lags a fresh scale and leaves out terminating pods, which
    can still write during their grace period, so the reset guard cannot rely
    on it.
    """
    deployment = apps.read_namespaced_deployment(name=name, namespace=namespace)
    if deployment.spec.replicas:
        return deployment.spec.replicas
    selector = ",".join(f"{key}={value}" for key, value in deployment.spec.selector.match_labels.items())
    pods = k8s_client.CoreV1Api().list_namespaced_pod(namespace=namespace, label_selector=selector)
    return len(pods.items)


def scale_deployment(apps: k8s_client.AppsV1Api, namespace: str, name: str, replicas: int) -> None:
    apps.patch_namespaced_deployment_scale(name=name, namespace=namespace, body={"spec": {"replicas": replicas}})


def deployment_replica_status(apps: k8s_client.AppsV1Api, namespace: str, name: str) -> tuple[int, int]:
    """Return (existing pods, ready pods) for a deployment."""
    deployment = apps.read_namespaced_deployment(name=name, namespace=namespace)
    return deployment.status.replicas or 0, deployment.status.ready_replicas or 0


class ShadowLaneStartConfig(dagster.Config):
    reset_state: bool = False
    consumer_replicas: int = 4
    processor_replicas: int = 8
    namespace: str = SHADOW_NAMESPACE
    consumer_deployment: str = SHADOW_CONSUMER_DEPLOYMENT
    processor_deployment: str = SHADOW_PROCESSOR_DEPLOYMENT
    shadow_db_env_var: str = SHADOW_DB_URL_ENV_VAR
    ready_timeout_seconds: int = 600


def _reset_shadow_state(context: dagster.OpExecutionContext, config: ShadowLaneStartConfig) -> None:
    apps = apps_api()
    for deployment in (config.consumer_deployment, config.processor_deployment):
        pods = deployment_pod_count(apps, config.namespace, deployment)
        if pods > 0:
            raise dagster.Failure(
                description=(
                    f"Deployment {deployment} still wants or has {pods} pod(s). "
                    "A reset while consumers run would leave the two paths inconsistent. "
                    "Run the stop-and-compare job first, then start with reset_state."
                )
            )

    tables = LEGACY_STATE_TABLES + PERSONHOG_STATE_TABLES
    context.log.info(f"Truncating {len(tables)} tables in the shadow persons database: {', '.join(tables)}")
    with closing(shadow_db_connection(config.shadow_db_env_var)) as connection:
        with connection, connection.cursor() as cursor:
            cursor.execute("SET application_name = 'dagster_personhog_shadow_lane'")
            cursor.execute("SET statement_timeout = '10min'")
            # One statement so the reset is atomic; CASCADE covers the FKs
            # between the person and distinct id tables on both sides.
            cursor.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
    context.log.info("Shadow persons database reset complete")


@dagster.op
def start_shadow_lane(context: dagster.OpExecutionContext, config: ShadowLaneStartConfig) -> None:
    if config.reset_state:
        _reset_shadow_state(context, config)
    else:
        context.log.info("reset_state is false, leaving the shadow persons database untouched")

    apps = apps_api()
    targets = [
        (config.consumer_deployment, config.consumer_replicas),
        (config.processor_deployment, config.processor_replicas),
    ]
    for deployment, replicas in targets:
        context.log.info(f"Scaling {config.namespace}/{deployment} to {replicas} replicas")
        scale_deployment(apps, config.namespace, deployment, replicas)

    deadline = time.monotonic() + config.ready_timeout_seconds
    pending = dict(targets)
    while pending and time.monotonic() < deadline:
        for deployment, replicas in list(pending.items()):
            _existing, ready = deployment_replica_status(apps, config.namespace, deployment)
            if ready >= replicas:
                context.log.info(f"{deployment} is ready with {ready} replica(s)")
                del pending[deployment]
        if pending:
            time.sleep(10)

    if pending:
        raise dagster.Failure(
            description=(
                f"Deployments not ready after {config.ready_timeout_seconds}s: {', '.join(pending)}. "
                "The scale was applied; check the pods in the lane namespace."
            )
        )

    context.add_output_metadata(
        {
            "reset_state": dagster.MetadataValue.bool(config.reset_state),
            "consumer_replicas": dagster.MetadataValue.int(config.consumer_replicas),
            "processor_replicas": dagster.MetadataValue.int(config.processor_replicas),
        }
    )


@dagster.job(tags={"owner": JobOwners.TEAM_INGESTION.value})
def personhog_shadow_lane_start_job():
    """Start the shadow lane consumers, optionally resetting the shadow persons database first.

    Run with default config to resume consuming from the committed offsets.
    Set ops.start_shadow_lane.config.reset_state to true to truncate both
    paths' tables before starting, which every fresh validation run needs.
    The reset refuses to run while the lane has pods.
    """
    start_shadow_lane()
