import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from unittest import mock

from flaky import flaky

from posthog.models.team.team import Team
from posthog.tasks.test.test_usage_report import freeze_time
from posthog.temporal.data_imports.settings import import_data_activity_sync
from posthog.temporal.data_imports.workflow_activities.import_data_sync import ImportDataActivityInputs

from products.data_warehouse.backend.models.credential import DataWarehouseCredential
from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.ssh_tunnel import SSHTunnel
from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.data_warehouse.backend.types import ExternalDataSourceType


def _setup(team: Team, job_inputs: dict[Any, Any]) -> ImportDataActivityInputs:
    source = ExternalDataSource.objects.create(
        team=team,
        source_id="source_id",
        connection_id="connection_id",
        status=ExternalDataSource.Status.COMPLETED,
        source_type=ExternalDataSourceType.POSTGRES,
        job_inputs=job_inputs,
    )
    credentials = DataWarehouseCredential.objects.create(access_key="blah", access_secret="blah", team=team)
    warehouse_table = DataWarehouseTable.objects.create(
        name="table_1",
        format="Parquet",
        team=team,
        external_data_source=source,
        external_data_source_id=source.id,
        credential=credentials,
        url_pattern="https://bucket.s3/data/*",
        columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
    )
    schema = ExternalDataSchema.objects.create(
        team=team,
        name="table_1",
        source=source,
        table=warehouse_table,
        should_sync=True,
        status=ExternalDataSchema.Status.COMPLETED,
        last_synced_at="2024-01-01",
    )
    job = ExternalDataJob.objects.create(
        team=team,
        pipeline=source,
        schema=schema,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=0,
        workflow_id="some_workflow_id",
        pipeline_version=ExternalDataJob.PipelineVersion.V1,
    )

    return ImportDataActivityInputs(team_id=team.pk, schema_id=schema.pk, source_id=source.pk, run_id=str(job.pk))


@pytest.mark.django_db(transaction=True)
def test_job_inputs_with_whitespace(activity_environment, team, **kwargs):
    job_inputs = {
        "host": " host.com   ",
        "port": 5432,
        "user": "Username   ",
        "password": "   password",
        "database": "  database",
        "schema": "schema       ",
    }

    activity_inputs = _setup(team, job_inputs)

    with (
        mock.patch("posthog.temporal.data_imports.sources.postgres.source.postgres_source") as mock_postgres_source,
        mock.patch("posthog.temporal.data_imports.workflow_activities.import_data_sync._run"),
    ):
        activity_environment.run(import_data_activity_sync, activity_inputs)

        mock_postgres_source.assert_called_once_with(
            tunnel=mock.ANY,
            user="Username",
            password="password",
            database="database",
            sslmode="prefer",
            schema="schema",
            table_names=["table_1"],
            should_use_incremental_field=False,
            logger=mock.ANY,
            db_incremental_field_last_value=None,
            incremental_field=None,
            incremental_field_type=None,
            chunk_size_override=None,
            team_id=team.id,
        )


@pytest.mark.django_db(transaction=True)
def test_postgres_source_without_ssh_tunnel(activity_environment, team, **kwargs):
    job_inputs = {
        "host": "host.com",
        "port": 5432,
        "user": "Username",
        "password": "password",
        "database": "database",
        "schema": "schema",
    }

    activity_inputs = _setup(team, job_inputs)

    with (
        mock.patch("posthog.temporal.data_imports.sources.postgres.source.postgres_source") as mock_postgres_source,
        mock.patch("posthog.temporal.data_imports.workflow_activities.import_data_sync._run"),
    ):
        activity_environment.run(import_data_activity_sync, activity_inputs)

        mock_postgres_source.assert_called_once_with(
            tunnel=mock.ANY,
            user="Username",
            password="password",
            database="database",
            sslmode="prefer",
            schema="schema",
            table_names=["table_1"],
            should_use_incremental_field=False,
            logger=mock.ANY,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            chunk_size_override=None,
            team_id=team.id,
        )


@pytest.mark.django_db(transaction=True)
def test_postgres_source_with_ssh_tunnel_disabled(activity_environment, team, **kwargs):
    job_inputs = {
        "host": "host.com",
        "port": "5432",
        "user": "Username",
        "password": "password",
        "database": "database",
        "schema": "schema",
        "ssh_tunnel": {
            "enabled": False,
            "host": "",
            "port": "",
            "auth_type": {
                "selection": "",
                "username": "",
                "password": "",
                "private_key": "",
                "passphrase": "",
            },
        },
    }

    activity_inputs = _setup(team, job_inputs)

    with (
        mock.patch("posthog.temporal.data_imports.sources.postgres.source.postgres_source") as mock_postgres_source,
        mock.patch("posthog.temporal.data_imports.workflow_activities.import_data_sync._run"),
    ):
        activity_environment.run(import_data_activity_sync, activity_inputs)

        mock_postgres_source.assert_called_once_with(
            tunnel=mock.ANY,
            user="Username",
            password="password",
            database="database",
            sslmode="prefer",
            schema="schema",
            table_names=["table_1"],
            should_use_incremental_field=False,
            logger=mock.ANY,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            chunk_size_override=None,
            team_id=team.id,
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@flaky(max_runs=3, min_passes=1)
def test_postgres_source_with_ssh_tunnel_enabled(activity_environment, team, **kwargs):
    job_inputs = {
        "host": "host.com",
        "port": "5432",
        "user": "Username",
        "password": "password",
        "database": "database",
        "schema": "schema",
        "ssh_tunnel": {
            "enabled": True,
            "host": "other-host.com",
            "port": "55550",
            "auth_type": {
                "selection": "password",
                "username": "username",
                "password": "password",
                "private_key": "",
                "passphrase": "",
            },
        },
    }

    activity_inputs = _setup(team, job_inputs)

    def mock_get_tunnel(self_class, host, port):
        class MockedTunnel:
            local_bind_host: str = "other-host.com"
            local_bind_port: int = 55550

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, exc_traceback):
                pass

        return MockedTunnel()

    with (
        mock.patch("posthog.temporal.data_imports.sources.postgres.source.postgres_source") as mock_postgres_source,
        mock.patch("posthog.temporal.data_imports.workflow_activities.import_data_sync._run"),
        mock.patch.object(SSHTunnel, "get_tunnel", mock_get_tunnel),
    ):
        activity_environment.run(import_data_activity_sync, activity_inputs)

        mock_postgres_source.assert_called_once_with(
            tunnel=mock.ANY,
            user="Username",
            password="password",
            database="database",
            sslmode="prefer",
            schema="schema",
            table_names=["table_1"],
            should_use_incremental_field=False,
            logger=mock.ANY,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            chunk_size_override=None,
            team_id=team.id,
        )


@pytest.mark.django_db(transaction=True)
def test_report_heartbeat_timeout_first_attempt(team):
    logger = mock.MagicMock()

    activity_inputs = ImportDataActivityInputs(
        team_id=team.pk, schema_id=uuid.uuid4(), source_id=uuid.uuid4(), run_id="run_id"
    )

    mock_info = mock.MagicMock()
    mock_info.attempt = 1  # First attempt
    mock_info.heartbeat_timeout = timedelta(seconds=10)
    mock_info.current_attempt_scheduled_time = datetime.now()

    with mock.patch(
        "posthog.temporal.data_imports.workflow_activities.import_data_sync.activity.info", return_value=mock_info
    ) as mock_activity_info:
        from posthog.temporal.data_imports.workflow_activities.import_data_sync import _report_heartbeat_timeout

        _report_heartbeat_timeout(activity_inputs, logger)

        mock_activity_info.assert_called_once()
        logger.debug.assert_any_call("Checking for heartbeat timeout reporting...")
        logger.debug.assert_any_call(f"First attempt of activity, no heartbeat timeout to report.")


@pytest.mark.django_db(transaction=True)
def test_report_heartbeat_timeout_no_heartbeat_timeout(team):
    logger = mock.MagicMock()

    activity_inputs = ImportDataActivityInputs(
        team_id=team.pk, schema_id=uuid.uuid4(), source_id=uuid.uuid4(), run_id="run_id"
    )

    mock_info = mock.MagicMock()
    mock_info.attempt = 2
    mock_info.heartbeat_timeout = None  # No heartbeat timeout
    mock_info.current_attempt_scheduled_time = datetime.now()

    with mock.patch(
        "posthog.temporal.data_imports.workflow_activities.import_data_sync.activity.info", return_value=mock_info
    ) as mock_activity_info:
        from posthog.temporal.data_imports.workflow_activities.import_data_sync import _report_heartbeat_timeout

        _report_heartbeat_timeout(activity_inputs, logger)

        mock_activity_info.assert_called_once()
        logger.debug.assert_any_call("Checking for heartbeat timeout reporting...")
        logger.debug.assert_any_call(f"No heartbeat timeout set for this activity: {mock_info.heartbeat_timeout}")


@pytest.mark.django_db(transaction=True)
def test_report_heartbeat_timeout_no_current_attempt_scheduled_time(team):
    logger = mock.MagicMock()

    activity_inputs = ImportDataActivityInputs(
        team_id=team.pk, schema_id=uuid.uuid4(), source_id=uuid.uuid4(), run_id="run_id"
    )

    mock_info = mock.MagicMock()
    mock_info.attempt = 2
    mock_info.heartbeat_timeout = timedelta(seconds=10)
    mock_info.current_attempt_scheduled_time = None  # No current attempt scheduled time

    with mock.patch(
        "posthog.temporal.data_imports.workflow_activities.import_data_sync.activity.info", return_value=mock_info
    ) as mock_activity_info:
        from posthog.temporal.data_imports.workflow_activities.import_data_sync import _report_heartbeat_timeout

        _report_heartbeat_timeout(activity_inputs, logger)

        mock_activity_info.assert_called_once()
        logger.debug.assert_any_call("Checking for heartbeat timeout reporting...")
        logger.debug.assert_any_call(
            f"No current attempt scheduled time set for this activity: {mock_info.current_attempt_scheduled_time}"
        )


@pytest.mark.django_db(transaction=True)
def test_report_heartbeat_timeout_no_heartbeat_details(team):
    logger = mock.MagicMock()

    activity_inputs = ImportDataActivityInputs(
        team_id=team.pk, schema_id=uuid.uuid4(), source_id=uuid.uuid4(), run_id="run_id"
    )

    mock_info = mock.MagicMock()
    mock_info.attempt = 2
    mock_info.heartbeat_timeout = timedelta(seconds=10)
    mock_info.current_attempt_scheduled_time = datetime.now()
    mock_info.heartbeat_details = None  # No heartbeat details

    with mock.patch(
        "posthog.temporal.data_imports.workflow_activities.import_data_sync.activity.info", return_value=mock_info
    ) as mock_activity_info:
        from posthog.temporal.data_imports.workflow_activities.import_data_sync import _report_heartbeat_timeout

        _report_heartbeat_timeout(activity_inputs, logger)

        mock_activity_info.assert_called_once()
        logger.debug.assert_any_call("Checking for heartbeat timeout reporting...")
        logger.debug.assert_any_call(
            f"No heartbeat details found to analyze for timeout: {mock_info.heartbeat_details}"
        )


@pytest.mark.django_db(transaction=True)
def test_report_heartbeat_timeout_heartbeat_details_are_not_a_tuple(team):
    logger = mock.MagicMock()

    activity_inputs = ImportDataActivityInputs(
        team_id=team.pk, schema_id=uuid.uuid4(), source_id=uuid.uuid4(), run_id="run_id"
    )

    mock_info = mock.MagicMock()
    mock_info.attempt = 2
    mock_info.heartbeat_timeout = timedelta(seconds=10)
    mock_info.current_attempt_scheduled_time = datetime.now()
    mock_info.heartbeat_details = 123  # Not a tuple

    with mock.patch(
        "posthog.temporal.data_imports.workflow_activities.import_data_sync.activity.info", return_value=mock_info
    ) as mock_activity_info:
        from posthog.temporal.data_imports.workflow_activities.import_data_sync import _report_heartbeat_timeout

        _report_heartbeat_timeout(activity_inputs, logger)

        mock_activity_info.assert_called_once()
        logger.debug.assert_any_call("Checking for heartbeat timeout reporting...")
        logger.debug.assert_any_call(
            f"No heartbeat details found to analyze for timeout: {mock_info.heartbeat_details}"
        )


@pytest.mark.django_db(transaction=True)
def test_report_heartbeat_timeout_heartbeat_details_last_item_is_not_a_dict(team):
    logger = mock.MagicMock()

    activity_inputs = ImportDataActivityInputs(
        team_id=team.pk, schema_id=uuid.uuid4(), source_id=uuid.uuid4(), run_id="run_id"
    )

    mock_info = mock.MagicMock()
    mock_info.attempt = 2
    mock_info.heartbeat_timeout = timedelta(seconds=10)
    mock_info.current_attempt_scheduled_time = datetime.now()
    mock_info.heartbeat_details = ({"host": "value"}, "not_a_dict")  # Last item is not a dict

    with mock.patch(
        "posthog.temporal.data_imports.workflow_activities.import_data_sync.activity.info", return_value=mock_info
    ) as mock_activity_info:
        from posthog.temporal.data_imports.workflow_activities.import_data_sync import _report_heartbeat_timeout

        _report_heartbeat_timeout(activity_inputs, logger)

        mock_activity_info.assert_called_once()
        logger.debug.assert_any_call("Checking for heartbeat timeout reporting...")
        logger.debug.assert_any_call(
            f"Last heartbeat details not in expected format (dict). Found: {type(mock_info.heartbeat_details[-1])}: {mock_info.heartbeat_details[-1]}"
        )


@pytest.mark.django_db(transaction=True)
def test_report_heartbeat_timeout_heartbeat_details_missing_host_or_ts(team):
    logger = mock.MagicMock()

    activity_inputs = ImportDataActivityInputs(
        team_id=team.pk, schema_id=uuid.uuid4(), source_id=uuid.uuid4(), run_id="run_id"
    )

    mock_info = mock.MagicMock()
    mock_info.attempt = 2
    mock_info.heartbeat_timeout = timedelta(seconds=10)
    mock_info.current_attempt_scheduled_time = datetime.now()
    mock_info.heartbeat_details = ({"some_other_key": "value"},)  # Missing 'ts' and 'host' key

    with mock.patch(
        "posthog.temporal.data_imports.workflow_activities.import_data_sync.activity.info", return_value=mock_info
    ) as mock_activity_info:
        from posthog.temporal.data_imports.workflow_activities.import_data_sync import _report_heartbeat_timeout

        _report_heartbeat_timeout(activity_inputs, logger)

        mock_activity_info.assert_called_once()
        logger.debug.assert_any_call("Checking for heartbeat timeout reporting...")
        logger.debug.assert_any_call(f"Last heartbeat was {mock_info.heartbeat_details[-1]}")
        logger.debug.assert_any_call(f"Incomplete heartbeat details. No host or timestamp found.")


@pytest.mark.django_db(transaction=True)
def test_report_heartbeat_timeout_heartbeat_within_timeout(team):
    logger = mock.MagicMock()

    activity_inputs = ImportDataActivityInputs(
        team_id=team.pk, schema_id=uuid.uuid4(), source_id=uuid.uuid4(), run_id="run_id"
    )

    mock_info = mock.MagicMock()
    mock_info.attempt = 2
    mock_info.heartbeat_timeout = timedelta(seconds=10)
    mock_info.current_attempt_scheduled_time = datetime.now()
    mock_info.heartbeat_details = ({"host": "value", "ts": datetime.now().timestamp()},)  # Valid heartbeat details

    with mock.patch(
        "posthog.temporal.data_imports.workflow_activities.import_data_sync.activity.info", return_value=mock_info
    ) as mock_activity_info:
        from posthog.temporal.data_imports.workflow_activities.import_data_sync import _report_heartbeat_timeout

        _report_heartbeat_timeout(activity_inputs, logger)

        mock_activity_info.assert_called_once()
        logger.debug.assert_any_call("Checking for heartbeat timeout reporting...")
        logger.debug.assert_any_call(f"Last heartbeat was {mock_info.heartbeat_details[-1]}")
        logger.debug.assert_any_call("Last heartbeat was within the heartbeat timeout window. No action needed.")


@pytest.mark.django_db(transaction=True)
def test_report_heartbeat_timeout_heartbeat_not_within_timeout(team):
    logger = mock.MagicMock()

    activity_inputs = ImportDataActivityInputs(
        team_id=team.pk, schema_id=uuid.uuid4(), source_id=uuid.uuid4(), run_id="run_id"
    )

    with freeze_time("2024-01-01 12:00:00"):
        past_time = datetime.now() - timedelta(seconds=30)

        mock_info = mock.MagicMock()
        mock_info.attempt = 2
        mock_info.heartbeat_timeout = timedelta(seconds=10)
        mock_info.current_attempt_scheduled_time = datetime.now()
        mock_info.heartbeat_details = ({"host": "value", "ts": past_time.timestamp()},)  # Heartbeat older than timeout

        with (
            mock.patch(
                "posthog.temporal.data_imports.workflow_activities.import_data_sync.activity.info",
                return_value=mock_info,
            ) as mock_activity_info,
            mock.patch(
                "posthog.temporal.data_imports.workflow_activities.import_data_sync.posthoganalytics.capture"
            ) as mock_posthog_capture,
        ):
            from posthog.temporal.data_imports.workflow_activities.import_data_sync import _report_heartbeat_timeout

            _report_heartbeat_timeout(activity_inputs, logger)

            mock_activity_info.assert_called_once()
            logger.debug.assert_any_call("Checking for heartbeat timeout reporting...")
            logger.debug.assert_any_call(f"Last heartbeat was {mock_info.heartbeat_details[-1]}")
            logger.debug.assert_any_call(
                "Last heartbeat was longer ago than the heartbeat timeout allows. Likely due to a pod OOM or restart.",
                last_heartbeat_host="value",
                last_heartbeat_timestamp=past_time.timestamp(),
                gap_between_beats=30.0,
                heartbeat_timeout_seconds=mock_info.heartbeat_timeout.total_seconds(),
            )

            mock_posthog_capture.assert_called_once_with(
                "dwh_pod_heartbeat_timeout",
                distinct_id=None,
                properties={
                    "team_id": activity_inputs.team_id,
                    "schema_id": str(activity_inputs.schema_id),
                    "source_id": str(activity_inputs.source_id),
                    "run_id": activity_inputs.run_id,
                    "host": "value",
                    "gap_between_beats": 30.0,
                    "heartbeat_timeout_seconds": mock_info.heartbeat_timeout.total_seconds(),
                    "task_queue": mock_info.task_queue,
                    "workflow_id": mock_info.workflow_id,
                    "workflow_run_id": mock_info.workflow_run_id,
                    "workflow_type": mock_info.workflow_type,
                    "attempt": mock_info.attempt,
                },
            )
