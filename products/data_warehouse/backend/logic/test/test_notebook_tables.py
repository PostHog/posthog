from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.cache import cache

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.data_warehouse.backend.logic.notebook_tables import (
    NotebookTableError,
    build_notebook_table_s3_key,
    build_notebook_table_staging_s3_key,
    build_notebook_table_url_pattern,
    save_notebook_table,
    validate_notebook_table_name,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

COLUMNS = {"score": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "valid": True}}


class TestValidateNotebookTableName(BaseTest):
    @parameterized.expand(
        [
            ("written_by_a_notebook", "scores", True, None),
            ("fresh_name", "fresh_scores", False, None),
            ("bad_characters", "my-scores", False, "starts with a letter"),
            ("posthog_table", "events", False, "already exists"),
            ("another_table", "scores", False, "a notebook didn't create it"),
        ]
    )
    def test_name_rules(self, _name: str, table_name: str, notebook_owned: bool, error: str | None) -> None:
        DataWarehouseTable.objects.create(
            team_id=self.team.id,
            name="scores",
            format="Parquet",
            url_pattern=(
                build_notebook_table_url_pattern(self.team.id, "scores")
                if notebook_owned
                else "https://bucket.example.com/upload.parquet"
            ),
        )
        if error is None:
            validate_notebook_table_name(self.team.id, table_name, self.user.id)
        else:
            with self.assertRaisesRegex(NotebookTableError, error):
                validate_notebook_table_name(self.team.id, table_name, self.user.id)

    @parameterized.expand([("replace", True), ("create", False)])
    def test_refuses_a_user_without_warehouse_edit_access(self, _name: str, table_exists: bool) -> None:
        table = DataWarehouseTable.objects.create(
            team_id=self.team.id,
            name="scores",
            format="Parquet",
            url_pattern=build_notebook_table_url_pattern(self.team.id, "scores"),
        )
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save(update_fields=["level"])
        AccessControl.objects.create(
            team=self.team,
            # Resource-level warehouse rules live on the warehouse_objects umbrella.
            resource="warehouse_table" if table_exists else "warehouse_objects",
            resource_id=str(table.id) if table_exists else None,
            organization_member=self.organization_membership,
            access_level="viewer",
        )
        cache.clear()

        with self.assertRaisesRegex(NotebookTableError, "permission"):
            validate_notebook_table_name(self.team.id, "scores" if table_exists else "fresh_scores", self.user.id)


class TestSaveNotebookTable(BaseTest):
    def _save(self, run_id: str, s3: MagicMock, columns: dict | Exception = COLUMNS) -> str:
        with (
            patch("products.data_warehouse.backend.logic.notebook_tables._s3_client", return_value=s3),
            patch.object(
                DataWarehouseTable,
                "get_columns",
                side_effect=columns if isinstance(columns, Exception) else None,
                return_value=columns,
            ),
            patch("products.data_warehouse.backend.logic.notebook_tables.validate_data_warehouse_table_columns"),
        ):
            return save_notebook_table(self.team.id, "scores", self.user.id, run_id)

    def test_publishes_the_staged_object_and_reuses_the_table(self):
        s3 = MagicMock()

        first_id = self._save("run-1", s3)
        second_id = self._save("run-2", s3, columns={"label": COLUMNS["score"]})

        self.assertEqual(first_id, second_id)
        table = DataWarehouseTable.objects.get(id=first_id)
        self.assertEqual(table.url_pattern, build_notebook_table_url_pattern(self.team.id, "scores"))
        self.assertEqual(list(table.columns), ["label"])
        live_key = build_notebook_table_s3_key(self.team.id, "scores")
        self.assertEqual([call.args[2] for call in s3.copy.call_args_list], [live_key, live_key])

    def test_unreadable_upload_never_replaces_the_live_object(self):
        s3 = MagicMock()
        table_id = self._save("run-1", s3)

        with self.assertRaises(NotebookTableError):
            self._save("run-2", s3, columns=Exception("bad column"))

        self.assertEqual(s3.copy.call_count, 1)
        s3.delete_object.assert_called_with(
            Bucket=settings.DATAWAREHOUSE_BUCKET,
            Key=build_notebook_table_staging_s3_key(self.team.id, "scores", "run-2"),
        )
        self.assertEqual(list(DataWarehouseTable.objects.get(id=table_id).columns), ["score"])
