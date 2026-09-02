from posthog.test.base import APIBaseTest
from unittest.mock import patch

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_warehouse.backend.presentation.views.saved_query import (
    CheckIncrementalThrottle,
    DataWarehouseSavedQueryViewSet,
)

GROUPED = "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY day"
CONFIG = {"enabled": True, "incremental_key": "day", "unique_key": ["day"]}


class TestSavedQueryIncremental(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/environments/{self.team.pk}/warehouse_saved_queries/{suffix}"

    def _create(self, query: str = GROUPED, incremental: dict | None = None):
        payload: dict = {"name": "daily_events", "query": {"kind": "HogQLQuery", "query": query}}
        if incremental is not None:
            payload["incremental"] = incremental
        return self.client.post(self._url(), payload)

    def test_saving_an_eligible_incremental_config_round_trips(self):
        response = self._create(incremental=CONFIG)

        assert response.status_code == 201, response.json()
        saved_query = DataWarehouseSavedQuery.objects.get(id=response.json()["id"])
        assert saved_query.incremental_config == {**CONFIG, "lookback_seconds": 0}
        assert response.json()["incremental"]["incremental_key"] == "day"

    def test_an_ineligible_query_is_rejected_with_the_reason(self):
        """The 400 has to name the construct, or the user has no way to fix it."""
        response = self._create(
            query="SELECT toStartOfDay(timestamp) AS day, event, count() AS c FROM events GROUP BY day, event",
            incremental=CONFIG,
        )

        assert response.status_code == 400
        assert response.json()["attr"] == "incremental"
        assert "GROUP BY" in response.json()["detail"]

    def test_a_disabled_config_skips_the_eligibility_check(self):
        """Turning it off must never be blocked by why it could not be turned on."""
        response = self._create(
            query="SELECT toStartOfDay(timestamp) AS day, event, count() AS c FROM events GROUP BY day, event",
            incremental={**CONFIG, "enabled": False},
        )

        assert response.status_code == 201, response.json()

    @patch(
        "products.data_warehouse.backend.presentation.views.saved_query.saved_query_workflow_exists", return_value=False
    )
    def test_incremental_state_is_read_only(self, _workflow_exists):
        created = self._create(incremental=CONFIG)
        saved_query_id = created.json()["id"]

        response = self.client.patch(
            self._url(f"{saved_query_id}/"),
            {"incremental_state": {"watermark": "2026-01-01T00:00:00+00:00"}},
        )

        assert response.status_code == 200, response.json()
        assert DataWarehouseSavedQuery.objects.get(id=saved_query_id).incremental_state is None

    @patch(
        "products.data_warehouse.backend.presentation.views.saved_query.saved_query_workflow_exists", return_value=False
    )
    def test_changing_the_query_alone_is_checked_against_the_stored_config(self, _workflow_exists):
        """Otherwise a query incremental cannot serve saves while the view stays incremental, and
        only fails at the next run."""
        created = self._create(incremental=CONFIG)

        response = self.client.patch(
            self._url(f"{created.json()['id']}/"),
            {
                "query": {
                    "kind": "HogQLQuery",
                    "query": "SELECT toStartOfDay(timestamp) AS day, event, count() AS c "
                    "FROM events GROUP BY day, event",
                }
            },
        )

        assert response.status_code == 400
        assert "GROUP BY" in response.json()["detail"]

    def test_check_incremental_reports_candidates_without_a_config(self):
        response = self.client.post(self._url("check_incremental/"), {"query": GROUPED})

        assert response.status_code == 200, response.json()
        assert response.json()["key_candidates"] == ["day"]
        assert response.json()["eligible"] is True

    def test_check_incremental_reports_blockers_for_a_config(self):
        response = self.client.post(
            self._url("check_incremental/"),
            {"query": f"{GROUPED} LIMIT 10", "incremental_key": "day", "unique_key": ["day"]},
        )

        assert response.status_code == 200, response.json()
        assert response.json()["eligible"] is False
        assert any("LIMIT" in blocker for blocker in response.json()["blockers"])

    def test_check_incremental_expands_star_to_real_columns(self):
        response = self.client.post(self._url("check_incremental/"), {"query": "SELECT * FROM events"})

        assert response.status_code == 200, response.json()
        assert "timestamp" in response.json()["key_candidates"]
        assert "*" not in response.json()["key_candidates"]

    def test_a_star_query_saves_with_a_config_naming_an_expanded_column(self):
        response = self._create(
            query="SELECT * FROM events",
            incremental={"enabled": True, "incremental_key": "timestamp", "unique_key": ["uuid"]},
        )

        assert response.status_code == 201, response.json()

    def test_check_incremental_rejects_an_oversized_query(self):
        # Parsing runs synchronously on an API worker, so the body has to be bounded before it
        # reaches the parser.
        response = self.client.post(self._url("check_incremental/"), {"query": "SELECT 1 -- " + "x" * (64 * 1024)})

        assert response.status_code == 400
        assert response.json()["attr"] == "query"

    def test_check_incremental_declares_a_per_caller_throttle(self):
        # A scripted flood of large bodies has to hit a rate limit; this fails if the throttle is
        # dropped from the action.
        assert DataWarehouseSavedQueryViewSet.check_incremental.kwargs["throttle_classes"] == [CheckIncrementalThrottle]

    def test_run_with_full_refresh_clears_the_watermark(self):
        """Dropping the watermark is the whole mechanism for a rebuild: the next run finds no
        progress to build on."""
        created = self._create(incremental=CONFIG)
        saved_query = DataWarehouseSavedQuery.objects.get(id=created.json()["id"])
        saved_query.incremental_state = {"watermark": "2026-01-01T00:00:00+00:00", "definition_fingerprint": "abc"}
        saved_query.save(update_fields=["incremental_state"])

        with (
            patch("products.data_warehouse.backend.presentation.views.saved_query.trigger_saved_query_schedule"),
            patch(
                "products.data_modeling.backend.logic.node_materialization.is_saved_query_on_v2_schedule",
                return_value=False,
            ),
        ):
            response = self.client.post(self._url(f"{saved_query.id}/run/"), {"full_refresh": True})

        assert response.status_code == 200, response.json()
        saved_query.refresh_from_db()
        assert "watermark" not in (saved_query.incremental_state or {})

    def test_run_without_full_refresh_leaves_the_watermark(self):
        created = self._create(incremental=CONFIG)
        saved_query = DataWarehouseSavedQuery.objects.get(id=created.json()["id"])
        saved_query.incremental_state = {"watermark": "2026-01-01T00:00:00+00:00"}
        saved_query.save(update_fields=["incremental_state"])

        with (
            patch("products.data_warehouse.backend.presentation.views.saved_query.trigger_saved_query_schedule"),
            patch(
                "products.data_modeling.backend.logic.node_materialization.is_saved_query_on_v2_schedule",
                return_value=False,
            ),
        ):
            response = self.client.post(self._url(f"{saved_query.id}/run/"), {})

        assert response.status_code == 200, response.json()
        saved_query.refresh_from_db()
        assert saved_query.incremental_state["watermark"] == "2026-01-01T00:00:00+00:00"
