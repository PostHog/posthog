from contextlib import contextmanager
from typing import List, Literal, Optional
from unittest.mock import patch

import pytest
from django.db import DEFAULT_DB_ALIAS
from django.db import Error as DjangoDatabaseError
from django.db import connections
from django.http import HttpResponse
from django.test import Client
from kafka.errors import KafkaError

from ee.kafka_client.client import TestKafkaProducer


@pytest.mark.django_db
def test_readyz_returns_200_if_everything_is_ok(client: Client):
    resp = get_readyz(client)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_readyz_endpoint_fails_for_kafka_connection_issues(client: Client):
    with simulate_kafka_cannot_connect():
        resp = get_readyz(client)

    assert resp.status_code == 503
    data = resp.json()
    assert data["kafka_connected"] == False


@pytest.mark.django_db
def test_readyz_supports_excluding_checks(client: Client):
    with simulate_postgres_error():
        resp = get_readyz(client, exclude=["postgres", "postgres_migrations_uptodate"])

    assert resp.status_code == 200
    data = resp.json()
    assert {
        check: status for check, status in data.items() if check in {"postgres", "postgres_migrations_uptodate"}
    } == {"postgres": False, "postgres_migrations_uptodate": False}


def test_readyz_doesnt_require_db(client: Client):
    """
    We don't want to fail to construct a response if we can't reach the
    database.
    """
    with simulate_postgres_error():
        resp = get_readyz(client)

    assert resp.status_code == 503
    data = resp.json()
    assert data["postgres"] == False


def test_livez_returns_200_and_doesnt_require_db(client: Client):
    """
    We want the livez endpoint to involve no database queries at all, it should
    just be an indicator that the python process hasn't hung.
    """

    with simulate_postgres_error():
        resp = get_livez(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data == {"http": True}


@pytest.mark.django_db
def test_readyz_accepts_roles_and_filters_by_relevant_services(client: Client):
    """
    We basically want to provide a mechanism that allows for checking if the
    process should be considered healthy based on the "role" it is playing. Here
    kafka being down should result in failure, but failure in postgres should not.
    """
    # events role
    with simulate_kafka_cannot_connect():
        resp = get_readyz(client=client, role="events")

    assert resp.status_code == 503

    with simulate_postgres_error():
        resp = get_readyz(client=client, role="events")

    assert resp.status_code == 200

    # web role
    with simulate_kafka_cannot_connect():
        resp = get_readyz(client=client, role="web")

    assert resp.status_code == 200

    with simulate_postgres_error():
        resp = get_readyz(client=client, role="web")

    assert resp.status_code == 503

    # worker role
    with simulate_kafka_cannot_connect():
        resp = get_readyz(client=client, role="worker")

    assert resp.status_code == 200

    with simulate_postgres_error():
        resp = get_readyz(client=client, role="worker")

    assert resp.status_code == 503


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
    assert resp.status_code == 400
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
