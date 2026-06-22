from posthog.test.base import APIBaseTest

from products.warehouse_sources.backend.models.column_annotation import WarehouseColumnAnnotation
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.table import DataWarehouseTable


class TestWarehouseColumnAnnotation(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.credential = DataWarehouseCredential.objects.create(access_key="k", access_secret="s", team=self.team)
        self.table = DataWarehouseTable.objects.create(
            name="stripe_charges",
            format="Parquet",
            team=self.team,
            credential=self.credential,
            url_pattern="https://bucket.s3/data/*",
        )

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.pk}/warehouse_column_annotations/{suffix}"

    def test_list_filters_by_table_id(self):
        other_table = DataWarehouseTable.objects.create(
            name="stripe_customers",
            format="Parquet",
            team=self.team,
            credential=self.credential,
            url_pattern="https://bucket.s3/data/*",
        )
        WarehouseColumnAnnotation.objects.for_team(self.team.pk).create(
            team=self.team,
            table=self.table,
            column_name="amount",
            description="charge amount in cents",
            description_source=WarehouseColumnAnnotation.DescriptionSource.AI_GENERATED,
        )
        WarehouseColumnAnnotation.objects.for_team(self.team.pk).create(
            team=self.team,
            table=other_table,
            column_name="email",
            description="customer email",
            description_source=WarehouseColumnAnnotation.DescriptionSource.AI_GENERATED,
        )

        response = self.client.get(self._url(f"?table_id={self.table.id}"))
        assert response.status_code == 200, response.json()
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["column_name"] == "amount"
        assert results[0]["description_source"] == "ai_generated"

    def test_patch_marks_as_user_edited(self):
        annotation = WarehouseColumnAnnotation.objects.for_team(self.team.pk).create(
            team=self.team,
            table=self.table,
            column_name="amount",
            description="charge amount in cents",
            description_source=WarehouseColumnAnnotation.DescriptionSource.AI_GENERATED,
        )

        response = self.client.patch(self._url(f"{annotation.id}/"), {"description": "amount the customer paid, USD"})
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["description"] == "amount the customer paid, USD"
        assert body["description_source"] == "user_edited"
        assert body["is_user_edited"] is True

        annotation.refresh_from_db()
        assert annotation.is_user_edited is True

    def test_create_sets_user_edited(self):
        response = self.client.post(
            self._url(),
            {"table": str(self.table.id), "column_name": "status", "description": "charge lifecycle status"},
        )
        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["description_source"] == "user_edited"
        assert body["is_user_edited"] is True

    def test_cannot_annotate_table_from_another_team(self):
        other_team = self.organization.teams.create(name="other")
        other_credential = DataWarehouseCredential.objects.create(access_key="k", access_secret="s", team=other_team)
        other_table = DataWarehouseTable.objects.create(
            name="secret",
            format="Parquet",
            team=other_team,
            credential=other_credential,
            url_pattern="https://bucket.s3/data/*",
        )

        response = self.client.post(
            self._url(),
            {"table": str(other_table.id), "column_name": "x", "description": "should fail"},
        )
        assert response.status_code == 400, response.json()
