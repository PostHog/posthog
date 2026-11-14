# explicit fixture import is needed as autodiscovery doesn't work due to package layout
from posthog.conftest import django_db_setup

__all__ = ["django_db_setup"]

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

import pytest
from posthog.test.base import reset_clickhouse_database_if_dirty, truncate_or_reset_clickhouse_database
from unittest.mock import patch

from django.conf import settings

import psycopg2
import psycopg2.extensions
from clickhouse_driver import Client
from psycopg.types.json import Jsonb

from posthog.clickhouse.cluster import ClickhouseCluster, get_cluster
from posthog.dags.clickhouse_cleanup import PG_CLEANUP_QUEUE_TABLE

# Import the shared Dagster PostgreSQL fixtures so they apply to all tests
# in this directory. Direct import (rather than pytest_plugins) is required
# because pytest disallows pytest_plugins in non-top-level conftest files.
from posthog.dags.tests.dagster_pg_fixtures import (  # noqa: F401
    _dagster_postgres_instance,
    _use_postgres_dagster_instance,
)
from posthog.dataclasses import frozen
from posthog.models import Organization, Team
from posthog.persons_db import persons_db_connection, persons_db_url

from products.cdp.backend.models.hog_functions import HogFunction


def insert_flag_evaluations(rows: list[tuple], client: Client) -> None:
    """Insert rows of (team_id, distinct_id, person_id, uuid, timestamp[, inserted_at]) into flag_evaluations.

    Six-element rows pin inserted_at, for tests whose deletion requests carry a created_at in the
    past: the sweep predicate only covers rows ingested before their request was created, and the
    column's DEFAULT stamps insert time, which would put the row out of every backdated request's
    scope.
    """
    columns = "team_id, distinct_id, person_id, uuid, timestamp"
    if rows and len(rows[0]) == 6:
        columns += ", inserted_at"
    client.execute(f"INSERT INTO writable_flag_evaluations ({columns}) VALUES", rows)


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


@contextmanager
def isolated_clickhouse_cluster(client_settings: Mapping[str, str] | None = None) -> Iterator[ClickhouseCluster]:
    """
    Cluster fixture with macOS Docker-compatible hostname resolution.
    Patches ClickhouseCluster to use host_name instead of host_address.
    """
    # The reset is unconditional because Kafka-engine arrivals do not advance the
    # dirty counter, so a late row would leak into the next test. There is no
    # teardown reset: the next test that uses this fixture resets on setup, and
    # reset_clickhouse_after_module covers the tests that run after the module.
    truncate_or_reset_clickhouse_database()
    with patch.object(
        ClickhouseCluster,
        "_ClickhouseCluster__get_cluster_hosts",
        _patched_get_cluster_hosts,
    ):
        yield get_cluster(client_settings=client_settings)


@pytest.fixture(scope="module", autouse=True)
def reset_clickhouse_after_module() -> Iterator[None]:
    yield
    reset_clickhouse_database_if_dirty()


@pytest.fixture
def cluster(django_db_setup) -> Iterator[ClickhouseCluster]:
    with isolated_clickhouse_cluster() as clickhouse_cluster:
        yield clickhouse_cluster


@pytest.fixture
def persons_database() -> Iterator[psycopg2.extensions.connection]:
    """A writer connection to the test persons DB with the cleanup queue emptied."""
    conn = psycopg2.connect(persons_db_url(writer=True))
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"TRUNCATE {PG_CLEANUP_QUEUE_TABLE}")
        conn.commit()
        yield conn
    finally:
        conn.close()


def geoip_template_source() -> str:
    """The Hog source of the current GeoIP template, as a function saved from it holds it."""
    template = (
        Path(__file__).parents[3] / "nodejs/src/cdp/templates/_transformations/geoip/geoip.template.ts"
    ).read_text()
    return template.split("code: `", 1)[1].split("`,", 1)[0].strip()


@frozen
class GeoipTeams:
    with_geoip: int
    without_geoip: int


@pytest.fixture
def geoip_teams(django_db_setup) -> Iterator[GeoipTeams]:
    organization = Organization.objects.create(name="geoip-backfill")
    with_geoip = Team.objects.create(organization=organization, name="with geoip")
    without_geoip = Team.objects.create(organization=organization, name="without geoip")
    HogFunction.objects.create(
        team=with_geoip,
        name="GeoIP",
        type="transformation",
        template_id="template-geoip",
        enabled=True,
        hog=geoip_template_source(),
    )
    yield GeoipTeams(with_geoip=with_geoip.id, without_geoip=without_geoip.id)
