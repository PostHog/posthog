from posthog.test.base import APIBaseTest

from products.warehouse_sources.backend.models.column_statistics import WarehouseColumnStatistics
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.table import DataWarehouseTable


class TestWarehouseColumnStatistics(APIBaseTest):
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
        return f"/api/projects/{self.team.pk}/warehouse_column_statistics/{suffix}"

    def _make_stat(self, table: DataWarehouseTable, column_name: str, **kwargs) -> WarehouseColumnStatistics:
        return WarehouseColumnStatistics.objects.for_team(self.team.pk).create(
            team=self.team, table=table, column_name=column_name, **kwargs
        )

    def test_list_filters_by_table_id(self):
        other_table = DataWarehouseTable.objects.create(
            name="stripe_customers",
            format="Parquet",
            team=self.team,
            credential=self.credential,
            url_pattern="https://bucket.s3/data/*",
        )
        self._make_stat(self.table, "amount", row_count=100, null_count=5, null_fraction=0.05, min_value="1")
        self._make_stat(other_table, "email", row_count=50)

        response = self.client.get(self._url(f"?table_id={self.table.id}"))
        assert response.status_code == 200, response.json()
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["column_name"] == "amount"
        assert results[0]["row_count"] == 100
        assert results[0]["null_fraction"] == 0.05
        assert results[0]["min_value"] == "1"

    def test_invalid_table_id_returns_empty_not_500(self):
        # A malformed table_id must not 500 (ValueError from the UUID cast) — it should filter to nothing.
        self._make_stat(self.table, "amount", row_count=1)
        response = self.client.get(self._url("?table_id=not-a-uuid"))
        assert response.status_code == 200, response.json()
        assert response.json()["results"] == []

    def test_read_only_rejects_writes(self):
        # Statistics are system-owned: the endpoint must never accept create/update/delete.
        stat = self._make_stat(self.table, "amount", row_count=1)
        assert self.client.post(self._url(), {"table": str(self.table.id), "column_name": "x"}).status_code == 405
        assert self.client.patch(self._url(f"{stat.id}/"), {"row_count": 9}).status_code == 405
        assert self.client.delete(self._url(f"{stat.id}/")).status_code == 405
