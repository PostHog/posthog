from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.hogql.database.database import _evaluate_warehouse_access_control_flag

from posthog.models import Organization, Team

from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource


class TestWarehouseSynchronization(BaseTest):
    def test_authorization_changes_reconcile_both_tenants_and_ignore_metadata(self) -> None:
        with (
            patch(
                "products.warehouse_sources.backend.authorization_signals.synchronization_enabled", return_value=True
            ),
            patch("products.warehouse_sources.backend.authorization_signals.schedule_organization_sync") as schedule,
        ):
            source = ExternalDataSource.objects.create(
                team=self.team, source_id="example-source", connection_id="example-connection", source_type="Zendesk"
            )
            table = DataWarehouseTable.objects.create(
                team=self.team, name="tickets", format="Parquet", columns={}, external_data_source=source
            )
            assert schedule.call_args.args[0] == self.organization.id
            schedule.reset_mock()
            table.columns = {"id": "String"}
            table.save(update_fields=["columns"])
            source.status = "Running"
            source.save(update_fields=["status"])
            schedule.assert_not_called()
            other_org = Organization.objects.create(name="Other organization")
            other_team = Team.objects.create(organization=other_org)
            table.team = other_team
            table.external_data_source = None
            table.save(update_fields=["team", "external_data_source"])
            assert {call.args[0] for call in schedule.call_args_list} == {self.organization.id, other_org.id}
            schedule.reset_mock()
            table.delete()
            assert schedule.call_args.args[0] == other_org.id

    def test_v2_enforces_warehouse_access_without_the_legacy_warehouse_flag(self) -> None:
        with (
            patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value="v2"),
            patch("posthog.hogql.database.database.feature_enabled_or_false", return_value=False),
        ):
            assert _evaluate_warehouse_access_control_flag(self.team)
        with (
            patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value="v1"),
            patch("posthog.hogql.database.database.feature_enabled_or_false", return_value=False),
        ):
            assert not _evaluate_warehouse_access_control_flag(self.team)
