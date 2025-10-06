import os
import warnings

import pytest

from django.conf import settings

import psycopg

from products.batch_exports.backend.tests.temporal.destinations.redshift.utils import MISSING_REQUIRED_ENV_VARS


@pytest.fixture
def redshift_config():
    """Fixture to provide a default configuration for Redshift batch exports.

    Reads required env vars to construct configuration, but if not present
    we default to local development PostgreSQL database, which should be mostly compatible.
    """
    if MISSING_REQUIRED_ENV_VARS:
        user = settings.PG_USER
        password = settings.PG_PASSWORD
        host = settings.PG_HOST
        port = int(settings.PG_PORT)
        warnings.warn("Missing required Redshift env vars. Running tests against local PG database.", stacklevel=1)

    else:
        user = os.environ["REDSHIFT_USER"]
        password = os.environ["REDSHIFT_PASSWORD"]
        host = os.environ["REDSHIFT_HOST"]
        port = int(os.environ.get("REDSHIFT_PORT", "5439"))

    return {
        "user": user,
        "password": password,
        "database": "posthog_batch_exports_test_2",
        "schema": "exports_test_schema",
        "host": host,
        "port": port,
    }


@pytest.fixture
def postgres_config(redshift_config):
    """We shadow this name so that setup_postgres_test_db works with Redshift."""
    psycopg._encodings._py_codecs["UNICODE"] = "utf-8"
    psycopg._encodings.py_codecs.update((k.encode(), v) for k, v in psycopg._encodings._py_codecs.items())

    yield redshift_config


@pytest.fixture
async def psycopg_connection(redshift_config, setup_postgres_test_db):
    """Fixture to manage a psycopg2 connection."""
    connection = await psycopg.AsyncConnection.connect(
        user=redshift_config["user"],
        password=redshift_config["password"],
        dbname=redshift_config["database"],
        host=redshift_config["host"],
        port=redshift_config["port"],
        # this is needed, otherwise query results are cached
        autocommit=True,
    )
    connection.prepare_threshold = None

    yield connection

    await connection.close()


@pytest.fixture
def properties_data_type(request) -> str:
    """A parametrizable fixture to configure the `str` `properties_data_type` setting."""
    try:
        return request.param
    except AttributeError:
        return "varchar"
