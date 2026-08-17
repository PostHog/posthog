import uuid
import datetime as dt

from posthog.test.base import BaseTest

from products.data_warehouse.backend.temporal.health_checks.external_data_failure import ExternalDataFailureCheck
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


class TestExternalDataFailureCheck(BaseTest):
    def _create_failed_schema(
        self, sync_type_config: dict | None = None, latest_error: str | None = None
    ) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()), connection_id=str(uuid.uuid4()), team=self.team, source_type="Postgres"
        )
        return ExternalDataSchema.objects.create(
            name="orders",
            team=self.team,
            source=source,
            status=ExternalDataSchema.Status.FAILED,
            latest_error=latest_error
            or "Source column type changed: 'total_cost' has values that no longer fit its stored type",
            sync_type_config=sync_type_config or {},
        )

    def _detected_schema_ids(self) -> set[str]:
        issues = ExternalDataFailureCheck().detect([self.team.id])
        return {result.payload["pipeline_id"] for result in issues.get(self.team.id, [])}

    def test_failed_schema_is_reported(self) -> None:
        schema = self._create_failed_schema()
        assert self._detected_schema_ids() == {str(schema.id)}

    def test_pending_auto_widen_resync_is_muted(self) -> None:
        fresh = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat()
        self._create_failed_schema(
            sync_type_config={"column_type_widened": {"column": "total_cost", "detected_at": fresh}}
        )
        assert self._detected_schema_ids() == set()

    def test_unrelated_failure_with_fresh_marker_still_alarms(self) -> None:
        fresh = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat()
        schema = self._create_failed_schema(
            sync_type_config={"column_type_widened": {"column": "total_cost", "detected_at": fresh}},
            latest_error="Couldn't connect to the source database",
        )
        assert self._detected_schema_ids() == {str(schema.id)}

    def test_stale_auto_widen_marker_still_alarms(self) -> None:
        # A marker older than the mute window means the automatic reset keeps getting blocked
        # (billing limits, paused schedule), so the failure must surface after all.
        stale = (dt.datetime.now(dt.UTC) - dt.timedelta(days=3)).isoformat()
        schema = self._create_failed_schema(
            sync_type_config={"column_type_widened": {"column": "total_cost", "detected_at": stale}}
        )
        assert self._detected_schema_ids() == {str(schema.id)}
