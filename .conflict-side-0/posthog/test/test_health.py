import random
import logging
from contextlib import contextmanager
from typing import Optional

import pytest
from unittest import mock
from unittest.mock import patch

from django.core.cache import cache
from django.db import (
    DEFAULT_DB_ALIAS,
    Error as DjangoDatabaseError,
    connections,
)
from django.http import HttpResponse
from django.test import Client

import psycopg2
import requests
import kombu.connection
import kombu.exceptions
import django_redis.exceptions
from kafka.errors import KafkaError

from posthog.health import logger
from posthog.kafka_client.client import KafkaProducerForTests


@pytest.mark.django_db
def test_readyz_returns_200_if_everything_is_ok(client: Client):
    resp = get_readyz(client)
    assert resp.status_code == 200, resp.content


@pytest.mark.django_db
def test_readyz_supports_excluding_checks(client: Client):
    with simulate_postgres_error():
        resp = get_readyz(client, exclude=["postgres", "postgres_flags", "postgres_migrations_uptodate"])

    assert resp.status_code == 200, resp.content
    data = resp.json()
    assert {
        check: status for check, status in data.items() if check in {"postgres", "postgres_migrations_uptodate"}
    } == {"postgres": False, "postgres_migrations_uptodate": False}


@pytest.mark.django_db
def test_readyz_can_handle_random_database_errors(client: Client):
    with simulate_postgres_psycopg2_error():
        resp = get_readyz(client)

    assert resp.status_code == 503, resp.content
    data = resp.json()
    assert {
        check: status for check, status in data.items() if check in {"postgres", "postgres_migrations_uptodate"}
    } == {"postgres": False, "postgres_migrations_uptodate": False}


@pytest.mark.django_db
def test_readyz_decide_can_handle_random_database_errors(client: Client):
    with simulate_postgres_psycopg2_error():
        resp = get_readyz(client, role="decide")

    assert resp.status_code == 200, resp.content
    data = resp.json()
    assert data == {"postgres_flags": False, "cache": True}


def test_livez_returns_200_and_doesnt_require_any_dependencies(client: Client):
    """
    We want the livez endpoint to involve no database queries at all, it should
    just be an indicator that the python process hasn't hung.
    """

    with (
        simulate_postgres_error(),
        simulate_kafka_cannot_connect(),
        simulate_clickhouse_cannot_connect(),
        simulate_celery_cannot_connect(),
        simulate_cache_cannot_connect(),
    ):
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

    with simulate_postgres_psycopg2_error():
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
def test_readyz_accepts_role_decide_and_filters_by_relevant_services(client: Client):
    with simulate_kafka_cannot_connect():
        resp = get_readyz(client=client, role="decide")

    assert resp.status_code == 200, resp.content

    with simulate_postgres_error():
        resp = get_readyz(client=client, role="decide")

    assert resp.status_code == 200, resp.content

    with simulate_clickhouse_cannot_connect():
        resp = get_readyz(client=client, role="decide")

    assert resp.status_code == 200, resp.content

    with simulate_celery_cannot_connect():
        resp = get_readyz(client=client, role="decide")

    assert resp.status_code == 200, resp.content

    with simulate_cache_cannot_connect():
        resp = get_readyz(client=client, role="decide")

    assert resp.status_code == 200, resp.content

    # only when both redis and postgres are down do we fail
    with simulate_cache_cannot_connect(), simulate_postgres_error():
        resp = get_readyz(client=client, role="decide")

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


def get_readyz(client: Client, exclude: Optional[list[str]] = None, role: Optional[str] = None) -> HttpResponse:
    return client.get("/_readyz", data={"exclude": exclude or [], "role": role or ""})


def get_livez(client: Client) -> HttpResponse:
    return client.get("/_livez")


def return_given_error_or_random(error: Optional[Exception] = None):
    """
    This randomly chooses between returning the given error or a random base exception. Useful
    for testing how we handle unexpected exceptions in health checks.
    """
    if random.choice([True, False]):
        return error

    return Exception(
        "random error: Make sure your checks support handling random errors! See `return_given_error_or_random` for more info."
    )


@contextmanager
def simulate_postgres_error():
    """
    Causes any call to cursor to raise the upper most Error in djangos db
    Exception hierachy
    """
    with patch.object(connections[DEFAULT_DB_ALIAS], "cursor") as cursor_mock:
        cursor_mock.side_effect = return_given_error_or_random(DjangoDatabaseError("failed to connect"))
        yield


@contextmanager
def simulate_postgres_psycopg2_error():
    """
    Causes psycopg2 to raise an error
    """
    with patch.object(connections[DEFAULT_DB_ALIAS], "cursor") as cursor_mock:
        cursor_mock.side_effect = return_given_error_or_random(psycopg2.OperationalError)
        yield


@contextmanager
def simulate_kafka_cannot_connect():
    """
    Causes instantiation of a kafka producer to raise a `KafkaError`.

    IMPORTANT: this is mocking the `KafkaProducerForTests`, itself a mock. I'm
    hoping that the real producer raises similarly, and that that behaviour
    doesn't change with version of the library. I have tested this manually
    however locally with real Kafka connection, and it seems to function as
    expected :fingerscrossed:
    """
    with patch.object(KafkaProducerForTests, "__init__") as init_mock:
        init_mock.side_effect = return_given_error_or_random(KafkaError("failed to connect"))
        yield


@contextmanager
def simulate_clickhouse_cannot_connect():
    """
    Simulates ClickHouse being unreachable by returning a 500 error response
    """

    with patch.object(requests, "get") as requests_mock:
        response = requests.Response()
        response.status_code = 500
        requests_mock.return_value = response
        yield


@contextmanager
def simulate_celery_cannot_connect():
    """
    Causes celery to raise a broker connection error
    """
    with patch.object(kombu.connection.Connection, "ensure_connection") as ensure_connection_mock:
        ensure_connection_mock.side_effect = return_given_error_or_random(kombu.exceptions.ConnectionError)
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
        has_key_mock.side_effect = return_given_error_or_random(
            django_redis.exceptions.ConnectionInterrupted(mock.Mock())
        )
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
