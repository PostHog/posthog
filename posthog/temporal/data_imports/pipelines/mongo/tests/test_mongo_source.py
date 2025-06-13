"""Tests for the MongoDB source.

NOTE: These tests require a MongoDB server to be running locally (or somewhere else).
Therefore these tests will only run if the required environment variables are set.

You can run a local MongoDB server using Docker:

```
docker run -d --name mongo-test -p 27017:27017 mongo:8.0
```

Then you can run these tests using:

```
OBJECT_STORAGE_ENDPOINT=http://localhost:19000 \
    MONGO_HOST=localhost \
    MONGO_DATABASE=test \
    pytest posthog/temporal/tests/data_imports/test_mongo_source.py
```

"""

import datetime as dt
import os
import uuid

import pytest
from bson import ObjectId

from posthog.temporal.data_imports.pipelines.mongo.mongo import MongoSourceConfig
from posthog.warehouse.models import ExternalDataSchema, ExternalDataSource

pytestmark = pytest.mark.usefixtures("minio_client")

REQUIRED_ENV_VARS = (
    "MONGO_HOST",
    "MONGO_DATABASE",
)

MONGO_COLLECTION_NAME = "test_collection"

TEST_DATA = [
    {
        "_id": ObjectId(),
        "name": "John Doe",
        "email": "john@example.com",
        "created_at": dt.datetime(2025, 1, 1),
        "age": 25,
    },
    {
        "_id": ObjectId(),
        "name": "Jane Smith",
        "email": "jane@example.com",
        "created_at": dt.datetime(2025, 1, 2),
        "age": 30,
    },
    {
        "_id": ObjectId(),
        "name": "Bob Wilson",
        "email": "bob@example.com",
        "created_at": dt.datetime(2025, 1, 3),
        "age": 35,
    },
]


def mongo_env_vars_are_set():
    if not all(env_var in os.environ for env_var in REQUIRED_ENV_VARS):
        return False
    return True


SKIP_IF_MISSING_MONGO_CREDENTIALS = pytest.mark.skipif(
    not mongo_env_vars_are_set(),
    reason="MongoDB connection credentials are not set",
)


@pytest.fixture
def mongo_config():
    return {
        "host": os.environ.get("MONGO_HOST", "localhost"),
        "port": int(os.environ.get("MONGO_PORT", "27017")),
        "database": os.environ.get("MONGO_DATABASE", "test"),
        "user": os.environ.get("MONGO_USER"),
        "password": os.environ.get("MONGO_PASSWORD"),
        "auth_source": os.environ.get("MONGO_AUTH_SOURCE", "admin"),
        "tls": os.environ.get("MONGO_TLS", "false").lower() == "true",
    }


@pytest.fixture
def external_data_source(mongo_config, team):
    source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="MongoDB",
        job_inputs=mongo_config,
    )
    return source


@pytest.fixture
def external_data_schema(external_data_source):
    return ExternalDataSchema.objects.create(
        name=MONGO_COLLECTION_NAME,
        team_id=external_data_source.team.pk,
        source_id=external_data_source.pk,
        should_sync=True,
    )


def test_mongo_source_config_loads():
    job_inputs = {
        "host": "host.com",
        "port": "27017",
        "user": "Username",
        "database": "database",
        "password": "password",
        "auth_source": "admin",
        "tls": False,
    }
    config = MongoSourceConfig.from_dict(job_inputs)

    assert config.host == "host.com"
    assert config.port == 27017
    assert config.user == "Username"
    assert config.password == "password"
    assert config.database == "database"
    assert config.auth_source == "admin"
    assert config.tls is False
    assert config.ssh_tunnel is None


def test_mongo_source_config_loads_int_port():
    job_inputs = {
        "host": "host.com",
        "port": 27017,
        "user": "Username",
        "database": "database",
        "password": "password",
    }
    config = MongoSourceConfig.from_dict(job_inputs)

    assert config.host == "host.com"
    assert config.port == 27017
    assert config.user == "Username"
    assert config.password == "password"
    assert config.database == "database"
    assert config.auth_source == "admin"
    assert config.tls is False
    assert config.ssh_tunnel is None
