# explicit fixture import is needed as autodiscovery doesn't work due to package layout
from posthog.conftest import django_db_setup

__all__ = ["django_db_setup"]

from collections.abc import Iterator

import pytest
from posthog.test.base import reset_clickhouse_database
from unittest.mock import patch

from django.conf import settings

from psycopg.types.json import Jsonb

from posthog.clickhouse.cluster import ClickhouseCluster, get_cluster

# Import the shared Dagster PostgreSQL fixtures so they apply to all tests
# in this directory. Direct import (rather than pytest_plugins) is required
# because pytest disallows pytest_plugins in non-top-level conftest files.
from posthog.dags.tests.dagster_pg_fixtures import (  # noqa: F401
    _dagster_postgres_instance,
    _use_postgres_dagster_instance,
)
from posthog.persons_db import persons_db_connection


def refresh_person_from_persons_db(person) -> None:
    """Reload a Person instance's mutable fields from the persons DB.

    These tests run with the personhog fake off (persons_db_direct) and seed via raw
    psycopg, so the Django ORM cannot read the persons DB. This mirrors the fields
    ``refresh_from_db()`` provided to the assertions, without touching the ORM.
    """
    with persons_db_connection(writer=True) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT properties, version, is_identified, properties_last_updated_at, properties_last_operation "
            f"FROM {settings.PERSON_TABLE_NAME} WHERE team_id = %s AND uuid = %s",
            (person.team_id, person.uuid),
        )
        row = cursor.fetchone()
    assert row is not None, f"person {person.uuid} not found in persons DB"
    (
        person.properties,
        person.version,
        person.is_identified,
        person.properties_last_updated_at,
        person.properties_last_operation,
    ) = row


def save_person_to_persons_db(person) -> None:
    """Persist a Person instance's properties/version to the persons DB via raw psycopg."""
    with persons_db_connection(writer=True) as conn, conn.cursor() as cursor:
        cursor.execute(
            f"UPDATE {settings.PERSON_TABLE_NAME} SET properties = %s, version = %s WHERE team_id = %s AND uuid = %s",
            (Jsonb(person.properties), person.version, person.team_id, person.uuid),
        )


def _patched_get_cluster_hosts(self, client, cluster, retry_policy=None):
    """
    Patch for local macOS Docker testing: use host_name instead of host_address.

    On macOS with Docker Desktop, system.clusters returns Docker-internal IPs
    (192.168.x.x) which aren't routable from the host. Using host_name returns
    "clickhouse" which resolves via /etc/hosts (set up by flox) to 127.0.0.1.
    """
    return client.execute(
        """
        SELECT host_name, port, shard_num, replica_num, getMacro('hostClusterType') as host_cluster_type, getMacro('hostClusterRole') as host_cluster_role
        FROM clusterAllReplicas(%(name)s, system.clusters)
        WHERE name = %(name)s and is_local
        ORDER BY shard_num, replica_num
        """,
        {"name": cluster},
    )


@pytest.fixture
def cluster(django_db_setup) -> Iterator[ClickhouseCluster]:
    """
    Cluster fixture with macOS Docker-compatible hostname resolution.
    Patches ClickhouseCluster to use host_name instead of host_address.
    """
    reset_clickhouse_database()
    try:
        with patch.object(
            ClickhouseCluster,
            "_ClickhouseCluster__get_cluster_hosts",
            _patched_get_cluster_hosts,
        ):
            yield get_cluster()
    finally:
        reset_clickhouse_database()
