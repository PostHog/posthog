import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from temporalio.client import ScheduleAlreadyRunningError

from products.data_warehouse.backend.logic.data_load.service import sync_external_data_job_workflow
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

_SERVICE_MODULE = "products.data_warehouse.backend.logic.data_load.service"


class TestSyncExternalDataJobWorkflow(BaseTest):
    def _schema(self) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )
        return ExternalDataSchema.objects.create(
            team_id=self.team.pk, source=source, name="public.users", should_sync=True
        )

    @parameterized.expand(
        [
            ("fresh_create", False),
            ("schedule_already_exists", True),
        ]
    )
    def test_create_without_trigger_never_fires_a_run(self, _name: str, already_exists: bool) -> None:
        # trigger_immediately=False exists for admin recovery: runs fired through the schedule
        # use its stored action, which is always billable, so recreating a schedule must not
        # fire one in either the fresh-create or the already-exists fallback branch.
        schema = self._schema()

        with (
            patch(f"{_SERVICE_MODULE}.sync_connect"),
            patch(
                f"{_SERVICE_MODULE}.create_schedule",
                side_effect=ScheduleAlreadyRunningError if already_exists else None,
            ) as mock_create,
            patch(f"{_SERVICE_MODULE}.update_schedule") as mock_update,
            patch(f"{_SERVICE_MODULE}.trigger_schedule") as mock_trigger,
        ):
            sync_external_data_job_workflow(schema, create=True, trigger_immediately=False)

        assert mock_create.call_args.kwargs["trigger_immediately"] is False
        if already_exists:
            mock_update.assert_called_once()
        mock_trigger.assert_not_called()

    def test_create_triggers_immediately_by_default(self) -> None:
        # Every pre-existing create=True caller (enabling sync on a schema, the reload/resync
        # heal) relies on the created schedule firing its first run right away.
        schema = self._schema()

        with (
            patch(f"{_SERVICE_MODULE}.sync_connect"),
            patch(f"{_SERVICE_MODULE}.create_schedule") as mock_create,
            patch(f"{_SERVICE_MODULE}.trigger_schedule") as mock_trigger,
        ):
            sync_external_data_job_workflow(schema, create=True)

        assert mock_create.call_args.kwargs["trigger_immediately"] is True
        mock_trigger.assert_not_called()
