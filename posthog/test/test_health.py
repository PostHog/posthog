import logging
from contextlib import contextmanager
from typing import List, Optional
from unittest import mock
from unittest.mock import patch

import django_redis.exceptions
import kombu.connection
import kombu.exceptions
import pytest
from clickhouse_driver.errors import Error as ClickhouseError
from django.core.cache import cache
from django.db import DEFAULT_DB_ALIAS
from django.db import Error as DjangoDatabaseError
from django.db import connections
from django.http import HttpResponse
from django.test import Client
from kafka.errors import KafkaError

from posthog.client import ch_pool
from posthog.health import logger
from posthog.kafka_client.client import TestKafkaProducer


@pytest.mark.django_db
def test_readyz_returns_200_if_everything_is_ok(client: Client):
    resp = get_readyz(client)
    assert resp.status_code == 200, resp.content


@pytest.mark.django_db
def test_readyz_supports_excluding_checks(client: Client):
    with simulate_postgres_error():
        resp = get_readyz(client, exclude=["postgres", "postgres_migrations_uptodate"])

    assert resp.status_code == 200, resp.content
    data = resp.json()
    assert {
        check: status for check, status in data.items() if check in {"postgres", "postgres_migrations_uptodate"}
    } == {"postgres": False, "postgres_migrations_uptodate": False}


def test_livez_returns_200_and_doesnt_require_any_dependencies(client: Client):
    """
    We want the livez endpoint to involve no database queries at all, it should
    just be an indicator that the python process hasn't hung.
    """

    with simulate_postgres_error(), simulate_kafka_cannot_connect(), simulate_clickhouse_cannot_connect(), simulate_celery_cannot_connect(), simulate_cache_cannot_connect():
        resp = get_livez(client)

    assert resp.status_code == 200, resp.content
    data = resp.json()
    assert data == {"http": True}


# Role based tests
#
# We basically want to provide a mechanism that allows for checking if the
# process should be considered healthy based on the "role" it is playing. Here
# kafka being down should result in failure, but failure in postgres should not.
#
# TODO: I've been quite explicit and verbose with the below, but it could be
# more readable how each role should behave.


@pytest.mark.django_db
def test_readyz_accepts_role_events_and_filters_by_relevant_services(client: Client):
    with simulate_kafka_cannot_connect():
        resp = get_readyz(client=client, role="events")

    assert resp.status_code == 503, resp.content

    with simulate_postgres_error():
        resp = get_readyz(client=client, role="events")

    assert resp.status_code == 200, resp.content

    with simulate_clickhouse_cannot_connect():
        resp = get_readyz(client=client, role="events")

    assert resp.status_code == 200, resp.content

    with simulate_celery_cannot_connect():
        resp = get_readyz(client=client, role="events")

    assert resp.status_code == 200, resp.content

    with simulate_cache_cannot_connect():
        resp = get_readyz(client=client, role="events")

    assert resp.status_code == 200, resp.content


@pytest.mark.django_db
def test_readyz_accepts_role_web_and_filters_by_relevant_services(client: Client):
    with simulate_kafka_cannot_connect():
        resp = get_readyz(client=client, role="web")

    assert resp.status_code == 200, resp.content

    with simulate_postgres_error():
        resp = get_readyz(client=client, role="web")

    assert resp.status_code == 503, resp.content

    with simulate_clickhouse_cannot_connect():
        resp = get_readyz(client=client, role="web")

    assert resp.status_code == 200, resp.content

    with simulate_celery_cannot_connect():
        resp = get_readyz(client=client, role="web")

    # NOTE: we don't want the web server to die if e.g. redis is down, there are
    # many things that still function without it
    assert resp.status_code == 200, resp.content

    with simulate_cache_cannot_connect():
        resp = get_readyz(client=client, role="web")

    # NOTE: redis being down is bad atm as e.g. Axes uses it to handle login
    # attempt rate limiting and doesn't fail gracefully
    assert resp.status_code == 503, resp.content


@pytest.mark.django_db
def test_readyz_accepts_role_worker_and_filters_by_relevant_services(client: Client):
    with simulate_kafka_cannot_connect():
        resp = get_readyz(client=client, role="worker")

    assert resp.status_code == 200, resp.content

    with simulate_postgres_error():
        resp = get_readyz(client=client, role="worker")

    assert resp.status_code == 503, resp.content

    with simulate_clickhouse_cannot_connect():
        resp = get_readyz(client=client, role="worker")

    assert resp.status_code == 503, resp.content

    with simulate_celery_cannot_connect():
        resp = get_readyz(client=client, role="worker")

    assert resp.status_code == 503, resp.content

    with simulate_cache_cannot_connect():
        resp = get_readyz(client=client, role="worker")

    assert resp.status_code == 200, resp.content


@pytest.mark.django_db
def test_readyz_accepts_no_role_and_fails_on_everything(client: Client):
    """
    If we don't specify any role, we assume we want all dependencies to be
    checked.
    """

    with simulate_kafka_cannot_connect():
        resp = get_readyz(client=client)

    assert resp.status_code == 503, resp.content

    with simulate_postgres_error():
        resp = get_readyz(client=client)

    assert resp.status_code == 503, resp.content

    with simulate_clickhouse_cannot_connect():
        resp = get_readyz(client=client)

    assert resp.status_code == 503, resp.content

    with simulate_celery_cannot_connect():
        resp = get_readyz(client=client)

    assert resp.status_code == 503, resp.content

    with simulate_cache_cannot_connect():
        resp = get_readyz(client=client)

    assert resp.status_code == 503, resp.content


@pytest.mark.django_db
def test_readyz_complains_if_role_does_not_exist(client: Client):
    """
    We want to be sure that, if we specify a role, we end up using the expected
    dependencies. We are liberal with the exclude attribute, such that we are a
    little flexible but for role we are a little more strict. We might change
    or remove the name of a service role, in this case we should keep the
    old service name is still available for lookup.
    """
    resp = get_readyz(client=client, role="some-unknown-role")
    assert resp.status_code == 400, resp.content
    data = resp.json()
    assert data["error"] == "InvalidRole"


def get_readyz(client: Client, exclude: Optional[List[str]] = None, role: Optional[str] = None) -> HttpResponse:
    return client.get("/_readyz", data={"exclude": exclude or [], "role": role or ""})


def get_livez(client: Client) -> HttpResponse:
    return client.get("/_livez")


@contextmanager
def simulate_postgres_error():
    """
    Causes any call to cursor to raise the upper most Error in djangos db
    Exception hierachy
    """
    with patch.object(connections[DEFAULT_DB_ALIAS], "cursor") as cursor_mock:
        cursor_mock.side_effect = DjangoDatabaseError  # This should be the most general
        yield


@contextmanager
def simulate_kafka_cannot_connect():
    """
    Causes instantiation of a kafka producer to raise a `KafkaError`.

    IMPORTANT: this is mocking the `TestKafkaProducer`, itselt a mock. I'm
    hoping that the real producer raises similarly, and that that behaviour
    doesn't change with version of the library. I have tested this manually
    however locally with real Kafka connection, and it seems to function as
    expected :fingerscrossed:
    """
    with patch.object(TestKafkaProducer, "__init__") as init_mock:
        init_mock.side_effect = KafkaError("failed to connect")
        yield


@contextmanager
def simulate_clickhouse_cannot_connect():
    """
    Causes the clickhouse client to raise a `ClickhouseError`

    TODO: ideally we'd simulate an error in a way that doesn't depend on the
    internal details of the service, i.e. we could actually bring clickhouse
    down, fail dns etc.
    """
    with patch.object(ch_pool, "get_client") as pool_mock:
        pool_mock.side_effect = ClickhouseError("failed to connect")
        yield


@contextmanager
def simulate_celery_cannot_connect():
    """
    Causes celery to raise a broker connection error
    """
    with patch.object(kombu.connection.Connection, "ensure_connection") as ensure_connection_mock:
        ensure_connection_mock.side_effect = kombu.exceptions.ConnectionError
        yield


@contextmanager
def simulate_cache_cannot_connect():
    """
    Causes the django cache library to raise a redis ConnectionError. I couldn't
    find a cache agnostic way to make this happen. In tests we're using local
    memory backend rather than redis, so this is not a perfect representation of
    reality.
    """
    with patch.object(cache, "has_key") as has_key_mock:
        has_key_mock.side_effect = django_redis.exceptions.ConnectionInterrupted(mock.Mock())
        yield


@pytest.fixture(autouse=True)
def debug_log_level():
    """
    We capture exceptions and log them at level debug. For easy debugging we set
    the logger level to debug so pytest can capture and display the output
    """
    original_level = logger.level
    logger.setLevel(logging.DEBUG)
    yield
    logger.setLevel(original_level)
