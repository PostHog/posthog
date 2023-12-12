import datetime as dt
import uuid

import pytest
from freezegun import freeze_time

from posthog.api.test.batch_exports.conftest import start_test_worker
from posthog.api.test.batch_exports.operations import (
    create_batch_export_ok,
    get_batch_export_log_entries,
    get_batch_export_run_log_entries,
)
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.batch_exports.models import (
    BatchExportLogEntryLevel,
    fetch_batch_export_log_entries,
)
from posthog.client import sync_execute
from posthog.temporal.common.client import sync_connect


def create_batch_export_log_entry(
    *,
    team_id: int,
    batch_export_id: str,
    run_id: str | None,
    message: str,
    level: BatchExportLogEntryLevel,
):
    from posthog.clickhouse.log_entries import INSERT_LOG_ENTRY_SQL

    sync_execute(
        INSERT_LOG_ENTRY_SQL,
        {
            "team_id": team_id,
            "log_source": "batch_exports",
            "log_source_id": batch_export_id,
            "instance_id": run_id,
            "timestamp": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "level": level,
            "message": message,
        },
    )


@pytest.fixture
def organization():
    organization = create_organization("Test Org")

    yield organization

    organization.delete()


@pytest.fixture
def team(organization):
    team = create_team(organization)

    yield team

    team.delete()


@pytest.fixture
def batch_export(client, organization, team):
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    temporal = sync_connect()

    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
        "start_at": "2023-07-19 00:00:00",
        "end_at": "2023-07-20 00:00:00",
    }
    with start_test_worker(temporal):
        batch_export = create_batch_export_ok(
            client,
            team.pk,
            batch_export_data,
        )

        yield batch_export


@pytest.mark.django_db
def test_simple_log_is_fetched(batch_export, team):
    """Test the simple case of fetching a batch export log entry."""
    with freeze_time("2023-09-22 01:00:00"):
        create_batch_export_log_entry(
            team_id=team.pk,
            batch_export_id=str(batch_export["id"]),
            run_id=None,
            message="Test log. Much INFO.",
            level=BatchExportLogEntryLevel.INFO,
        )

        results = fetch_batch_export_log_entries(
            team_id=team.pk,
            batch_export_id=batch_export["id"],
            after=dt.datetime(2023, 9, 22, 0, 59, 59),
            before=dt.datetime(2023, 9, 22, 1, 0, 1),
        )

    assert len(results) == 1
    assert results[0].message == "Test log. Much INFO."
    assert results[0].level == BatchExportLogEntryLevel.INFO
    assert results[0].batch_export_id == str(batch_export["id"])


@pytest.mark.django_db
@pytest.mark.parametrize(
    "level",
    [
        BatchExportLogEntryLevel.INFO,
        BatchExportLogEntryLevel.WARNING,
        BatchExportLogEntryLevel.ERROR,
        BatchExportLogEntryLevel.DEBUG,
    ],
)
def test_log_level_filter(batch_export, team, level):
    """Test fetching a batch export log entries of a particular level."""
    with freeze_time("2023-09-22 01:00:00"):
        for message in ("Test log 1", "Test log 2"):
            create_batch_export_log_entry(
                team_id=team.pk,
                batch_export_id=str(batch_export["id"]),
                run_id=None,
                message=message,
                level=level,
            )

    results = []
    timeout = 10
    start = dt.datetime.utcnow()

    while not results:
        results = fetch_batch_export_log_entries(
            team_id=team.pk,
            batch_export_id=batch_export["id"],
            level_filter=[level],
            after=dt.datetime(2023, 9, 22, 0, 59, 59),
            before=dt.datetime(2023, 9, 22, 1, 0, 1),
        )
        if (dt.datetime.utcnow() - start) > dt.timedelta(seconds=timeout):
            break

    results.sort(key=lambda record: record.message)

    assert len(results) == 2
    assert results[0].message == "Test log 1"
    assert results[0].level == level
    assert results[0].batch_export_id == str(batch_export["id"])
    assert results[1].message == "Test log 2"
    assert results[1].level == level
    assert results[1].batch_export_id == str(batch_export["id"])


@pytest.mark.django_db
@pytest.mark.parametrize(
    "level",
    [
        BatchExportLogEntryLevel.INFO,
        BatchExportLogEntryLevel.WARNING,
        BatchExportLogEntryLevel.ERROR,
        BatchExportLogEntryLevel.DEBUG,
    ],
)
def test_log_level_filter_with_lowercase(batch_export, team, level):
    """Test fetching a batch export log entries of a particular level."""
    with freeze_time("2023-09-22 01:00:00"):
        for message in ("Test log 1", "Test log 2"):
            create_batch_export_log_entry(
                team_id=team.pk,
                batch_export_id=str(batch_export["id"]),
                run_id=None,
                message=message,
                level=level.lower(),
            )

    results = []
    timeout = 10
    start = dt.datetime.utcnow()

    while not results:
        results = fetch_batch_export_log_entries(
            team_id=team.pk,
            batch_export_id=batch_export["id"],
            level_filter=[level],
            after=dt.datetime(2023, 9, 22, 0, 59, 59),
            before=dt.datetime(2023, 9, 22, 1, 0, 1),
        )
        if (dt.datetime.utcnow() - start) > dt.timedelta(seconds=timeout):
            break

    results.sort(key=lambda record: record.message)

    assert len(results) == 2
    assert results[0].message == "Test log 1"
    assert results[0].level == level
    assert results[0].batch_export_id == str(batch_export["id"])
    assert results[1].message == "Test log 2"
    assert results[1].level == level
    assert results[1].batch_export_id == str(batch_export["id"])


@pytest.mark.django_db
def test_batch_export_log_api(client, batch_export, team):
    """Test fetching batch export log entries using the API."""
    create_batch_export_log_entry(
        team_id=team.pk,
        batch_export_id=str(batch_export["id"]),
        run_id=str(uuid.uuid4()),
        message="Test log. Much INFO.",
        level=BatchExportLogEntryLevel.INFO,
    )
    create_batch_export_log_entry(
        team_id=team.pk,
        batch_export_id=str(batch_export["id"]),
        run_id=str(uuid.uuid4()),
        message="Test log. Much ERROR.",
        level=BatchExportLogEntryLevel.ERROR,
    )

    response = get_batch_export_log_entries(
        client,
        team_id=team.pk,
        batch_export_id=batch_export["id"],
    )

    json_response = response.json()
    results = json_response["results"]

    assert response.status_code == 200
    assert json_response["count"] == 2
    assert len(results) == 2
    # Logs are ordered by timestamp DESC, so ERROR log comes first.
    assert results[0]["message"] == "Test log. Much ERROR."
    assert results[0]["level"] == BatchExportLogEntryLevel.ERROR
    assert results[0]["batch_export_id"] == str(batch_export["id"])
    assert results[1]["message"] == "Test log. Much INFO."
    assert results[1]["level"] == BatchExportLogEntryLevel.INFO
    assert results[1]["batch_export_id"] == str(batch_export["id"])


@pytest.mark.django_db
def test_batch_export_run_log_api(client, batch_export, team):
    """Test fetching batch export run log entries using the API."""
    run_id = str(uuid.uuid4())

    create_batch_export_log_entry(
        team_id=team.pk,
        batch_export_id=str(batch_export["id"]),
        run_id=run_id,
        message="Test log. Much INFO.",
        level=BatchExportLogEntryLevel.INFO,
    )

    create_batch_export_log_entry(
        team_id=team.pk,
        batch_export_id=str(batch_export["id"]),
        # Logs from a different run shouldn't be in results.
        run_id=str(uuid.uuid4()),
        message="Test log. Much INFO.",
        level=BatchExportLogEntryLevel.INFO,
    )

    response = get_batch_export_run_log_entries(
        client,
        team_id=team.pk,
        batch_export_id=batch_export["id"],
        run_id=run_id,
    )

    json_response = response.json()
    results = json_response["results"]

    assert response.status_code == 200
    assert json_response["count"] == 1
    assert len(results) == 1
    assert results[0]["message"] == "Test log. Much INFO."
    assert results[0]["level"] == BatchExportLogEntryLevel.INFO
    assert results[0]["batch_export_id"] == str(batch_export["id"])


@pytest.mark.django_db
def test_batch_export_run_log_api_with_level_filter(client, batch_export, team):
    """Test fetching batch export run log entries using the API."""
    run_id = str(uuid.uuid4())

    create_batch_export_log_entry(
        team_id=team.pk,
        batch_export_id=str(batch_export["id"]),
        run_id=run_id,
        message="Test log. Much INFO.",
        level=BatchExportLogEntryLevel.INFO,
    )

    create_batch_export_log_entry(
        team_id=team.pk,
        batch_export_id=str(batch_export["id"]),
        run_id=run_id,
        message="Test log. Much DEBUG.",
        level=BatchExportLogEntryLevel.DEBUG,
    )

    response = get_batch_export_run_log_entries(
        client,
        team_id=team.pk,
        batch_export_id=batch_export["id"],
        run_id=run_id,
        level_filter="info",
    )

    json_response = response.json()
    results = json_response["results"]

    assert response.status_code == 200
    assert json_response["count"] == 1
    assert len(results) == 1
    assert results[0]["message"] == "Test log. Much INFO."
    assert results[0]["level"] == BatchExportLogEntryLevel.INFO
    assert results[0]["batch_export_id"] == str(batch_export["id"])
