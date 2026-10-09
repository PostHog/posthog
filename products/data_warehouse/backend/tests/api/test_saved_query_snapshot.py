from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

FLAG_CHECK = "products.data_warehouse.backend.presentation.views.saved_query.editing.modeling_api.snapshot_materialization_enabled"
QUERY = {"kind": "HogQLQuery", "query": "SELECT 1 AS customer_id, 'free' AS plan"}
SNAPSHOT = {"unique_key": ["customer_id"]}


class TestSavedQuerySnapshot(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/environments/{self.team.pk}/warehouse_saved_queries/{suffix}"

    @parameterized.expand([("flag_on", True, 201), ("flag_off", False, 400)])
    def test_snapshot_config_is_gated_by_its_own_flag(self, _name: str, enabled: bool, expected_status: int):
        with patch(FLAG_CHECK, return_value=enabled):
            response = self.client.post(self._url(), {"name": "plan_history", "query": QUERY, "snapshot": SNAPSHOT})

        assert response.status_code == expected_status, response.json()
        if enabled:
            saved_query = DataWarehouseSavedQuery.objects.get(id=response.json()["id"])
            assert saved_query.snapshot_config == SNAPSHOT
        else:
            assert response.json()["attr"] == "snapshot"

    def test_existing_snapshot_model_stays_editable_when_the_flag_is_off(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="plan_history", query=QUERY, snapshot_config=SNAPSHOT
        )

        with patch(FLAG_CHECK, return_value=False):
            response = self.client.patch(self._url(f"{saved_query.id}/"), {"name": "plan_history_renamed"})

        assert response.status_code == 200, response.json()

    def test_snapshot_key_change_is_refused_when_history_publishes_after_validation(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="plan_history", query=QUERY, snapshot_config=SNAPSHOT
        )

        def publish_first_generation(_team_id: int) -> bool:
            DataWarehouseSavedQuery.objects.filter(pk=saved_query.pk).update(
                snapshot_state={"generation_uri": "s3://bucket/generation", "last_run_id": "run"}
            )
            return True

        with patch(FLAG_CHECK, side_effect=publish_first_generation):
            response = self.client.patch(self._url(f"{saved_query.id}/"), {"snapshot": {"unique_key": ["plan"]}})

        assert response.status_code == 400, response.json()
        assert response.json()["attr"] == "snapshot"
        saved_query.refresh_from_db()
        assert saved_query.snapshot_config == SNAPSHOT
