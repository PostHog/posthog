from typing import Any, cast
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog, Trigger
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.data_modeling.backend.facade.contracts import (
    SavedQueryRepairConflictError,
    SavedQueryRepairForbiddenError,
    SavedQueryRepairInvalidError,
    SavedQueryRepairUnsupportedError,
)
from products.data_modeling.backend.logic.saved_query_repair import apply_saved_query_repair, prepare_saved_query_repair
from products.data_modeling.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

COLUMNS = {"id": {"hogql": "IntegerDatabaseField", "clickhouse": "UInt8", "valid": True}}
ORIGINAL_SQL = "SELECT 1 AS id"
PROPOSED_SQL = "SELECT 2 AS id"


class TestSavedQueryRepair(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="orders",
            query={"kind": "HogQLQuery", "query": ORIGINAL_SQL},
            columns=COLUMNS,
            column_order=["id"],
            incremental_config={"enabled": True, "incremental_key": "id", "unique_key": ["id"]},
            is_materialized=True,
        )
        self.enterContext(patch.object(DataWarehouseSavedQuery, "get_columns", return_value=COLUMNS))
        self.enterContext(patch.object(DataWarehouseSavedQuery, "get_s3_tables", return_value=[]))

    def test_proposal_validation_is_bounded_and_does_not_edit_the_view(self) -> None:
        plan = prepare_saved_query_repair(self.team.id, self.view.id, PROPOSED_SQL, user=self.user)

        self.view.refresh_from_db()
        assert plan.validation.rows_read == 0
        assert plan.validation.read_only is True
        assert plan.validation.business_equivalence_checked is False
        assert plan.original_query == ORIGINAL_SQL
        assert self.view.query == {"kind": "HogQLQuery", "query": ORIGINAL_SQL}

    def test_invalid_and_unsupported_repairs_are_rejected(self) -> None:
        with self.assertRaises(SavedQueryRepairInvalidError):
            prepare_saved_query_repair(self.team.id, self.view.id, "SELECT (", user=self.user)

        managed_viewset = DataWarehouseManagedViewSet.objects.create(team=self.team, kind="revenue_analytics")
        DataWarehouseSavedQuery.objects.filter(id=self.view.id).update(managed_viewset=managed_viewset)
        with self.assertRaises(SavedQueryRepairUnsupportedError):
            prepare_saved_query_repair(self.team.id, self.view.id, PROPOSED_SQL, user=self.user)

    def test_a_repair_that_changes_the_result_schema_is_rejected(self) -> None:
        changed_columns = {"other_id": {"hogql": "IntegerDatabaseField", "clickhouse": "UInt8", "valid": True}}

        with (
            patch.object(DataWarehouseSavedQuery, "get_columns", return_value=changed_columns),
            self.assertRaisesRegex(SavedQueryRepairInvalidError, "changes the result schema"),
        ):
            prepare_saved_query_repair(self.team.id, self.view.id, PROPOSED_SQL, user=self.user)

    def test_acceptance_refuses_a_stale_query_revision(self) -> None:
        plan = prepare_saved_query_repair(self.team.id, self.view.id, PROPOSED_SQL, user=self.user)
        DataWarehouseSavedQuery.objects.filter(id=self.view.id).update(query_revision=uuid4())

        with self.assertRaisesRegex(SavedQueryRepairConflictError, "changed after the SQL repair was proposed"):
            apply_saved_query_repair(
                self.team.id,
                self.view.id,
                original_query_revision=plan.original_query_revision,
                original_query_hash=plan.original_query_hash,
                proposed_query=plan.proposed_query,
                user=self.user,
                was_impersonated=False,
                trigger=Trigger(job_type="warehouse_suggestion", job_id="suggestion-1", payload={}),
            )

        self.view.refresh_from_db()
        assert self.view.query == {"kind": "HogQLQuery", "query": ORIGINAL_SQL}

    def test_acceptance_uses_the_audited_query_update_path_and_keeps_settings(self) -> None:
        plan = prepare_saved_query_repair(self.team.id, self.view.id, PROPOSED_SQL, user=self.user)
        before_config = self.view.incremental_config

        revision = apply_saved_query_repair(
            self.team.id,
            self.view.id,
            original_query_revision=plan.original_query_revision,
            original_query_hash=plan.original_query_hash,
            proposed_query=plan.proposed_query,
            user=self.user,
            was_impersonated=False,
            trigger=Trigger(job_type="warehouse_suggestion", job_id="suggestion-1", payload={}),
        )

        self.view.refresh_from_db()
        assert self.view.query == {"kind": "HogQLQuery", "query": PROPOSED_SQL}
        assert str(self.view.query_revision) == revision
        assert self.view.incremental_config == before_config
        log = ActivityLog.objects.get(
            team_id=self.team.id, scope="DataWarehouseSavedQuery", item_id=str(self.view.id), activity="updated"
        )
        detail = cast(dict[str, Any], log.detail)
        assert detail["trigger"]["job_type"] == "warehouse_suggestion"
        query_change = next(change for change in detail["changes"] if change["field"] == "query")
        assert query_change["before"] == {"kind": "HogQLQuery", "query": ORIGINAL_SQL}
        assert query_change["after"] == {"kind": "HogQLQuery", "query": PROPOSED_SQL}

    def test_a_viewer_cannot_apply_a_sql_repair(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        viewer = User.objects.create_and_join(self.organization, "viewer@example.com", "testtest")
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_view",
            resource_id=str(self.view.id),
            access_level="viewer",
            organization_member=OrganizationMembership.objects.get(user=viewer, organization=self.organization),
        )
        plan = prepare_saved_query_repair(self.team.id, self.view.id, PROPOSED_SQL, user=viewer)

        with self.assertRaisesRegex(SavedQueryRepairForbiddenError, "edit access"):
            apply_saved_query_repair(
                self.team.id,
                self.view.id,
                original_query_revision=plan.original_query_revision,
                original_query_hash=plan.original_query_hash,
                proposed_query=plan.proposed_query,
                user=viewer,
                was_impersonated=False,
                trigger=Trigger(job_type="warehouse_suggestion", job_id="suggestion-1", payload={}),
            )

        self.view.refresh_from_db()
        assert self.view.query == {"kind": "HogQLQuery", "query": ORIGINAL_SQL}
