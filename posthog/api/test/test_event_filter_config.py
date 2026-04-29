from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.event_filter_config import EventFilterConfig, EventFilterMode
from posthog.models.organization import Organization
from posthog.models.team.team import Team


def _cond(field: str = "event_name", operator: str = "exact", value: str = "$pageview") -> dict:
    return {"type": "condition", "field": field, "operator": operator, "value": value}


def _and(*children: dict) -> dict:
    return {"type": "and", "children": list(children)}


def _or(*children: dict) -> dict:
    return {"type": "or", "children": list(children)}


def _not(child: dict) -> dict:
    return {"type": "not", "child": child}


class TestEventFilterConfigAPI(APIBaseTest):
    def _url(self, team_id: int | None = None) -> str:
        return f"/api/environments/{team_id or self.team.id}/event_filter/"

    # -- List (GET) --

    def test_list_returns_204_when_no_config(self):
        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b""
        assert not EventFilterConfig.objects.filter(team=self.team).exists()

    def test_list_returns_existing_config(self):
        tree = _cond()
        EventFilterConfig.objects.create(team=self.team, mode=EventFilterMode.LIVE, filter_tree=tree)

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["mode"] == "live"
        assert data["filter_tree"] == tree
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    def test_list_does_not_create_config(self):
        self.client.get(self._url())
        self.client.get(self._url())

        assert not EventFilterConfig.objects.filter(team=self.team).exists()

    # -- Create (POST / upsert) --

    def _seed_config(self) -> dict:
        """Create a fully populated config and return the response data."""
        tree = _or(_cond(), _cond("distinct_id", "contains", "bot"))
        test_cases = [
            {"event_name": "$pageview", "expected_result": "drop"},
            {"event_name": "purchase", "expected_result": "ingest"},
        ]
        response = self.client.post(
            self._url(),
            data={"mode": "live", "filter_tree": tree, "test_cases": test_cases},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def test_create_upserts_mode(self):
        seed = self._seed_config()

        response = self.client.post(self._url(), data={"mode": "dry_run"}, format="json")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["mode"] == "dry_run"
        assert data["filter_tree"] == seed["filter_tree"]
        assert data["test_cases"] == seed["test_cases"]
        assert data["id"] == seed["id"]

    def test_create_upserts_filter_tree(self):
        seed = self._seed_config()
        new_tree = _cond("distinct_id", "exact", "user-1")
        new_test_cases = [
            {"distinct_id": "user-1", "expected_result": "drop"},
            {"distinct_id": "someone-else", "expected_result": "ingest"},
        ]

        response = self.client.post(
            self._url(), data={"filter_tree": new_tree, "test_cases": new_test_cases}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["filter_tree"] == new_tree
        assert data["test_cases"] == new_test_cases
        assert data["mode"] == seed["mode"]
        assert data["id"] == seed["id"]

    def test_create_upserts_test_cases(self):
        seed = self._seed_config()
        new_test_cases = [{"event_name": "$pageview", "expected_result": "drop"}]

        response = self.client.post(self._url(), data={"test_cases": new_test_cases}, format="json")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["test_cases"] == new_test_cases
        assert data["mode"] == seed["mode"]
        assert data["filter_tree"] == seed["filter_tree"]
        assert data["id"] == seed["id"]

    def test_create_clears_filter_tree(self):
        seed = self._seed_config()

        response = self.client.post(self._url(), data={"filter_tree": None, "test_cases": []}, format="json")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["filter_tree"] is None
        assert data["test_cases"] == []
        assert data["mode"] == seed["mode"]
        assert data["id"] == seed["id"]

    def test_create_clears_test_cases(self):
        seed = self._seed_config()

        response = self.client.post(self._url(), data={"test_cases": []}, format="json")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["test_cases"] == []
        assert data["filter_tree"] == seed["filter_tree"]
        assert data["id"] == seed["id"]

    def test_create_does_not_duplicate_config(self):
        self.client.post(self._url(), data={"mode": "disabled"}, format="json")
        self.client.post(self._url(), data={"mode": "live", "filter_tree": _cond()}, format="json")

        assert EventFilterConfig.objects.filter(team=self.team).count() == 1

    def test_create_prunes_filter_tree_on_save(self):
        tree = _and(_cond())
        response = self.client.post(self._url(), data={"filter_tree": tree}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["filter_tree"] == _cond()

    def test_create_timestamps_are_read_only(self):
        response = self.client.post(
            self._url(),
            data={"created_at": "2000-01-01T00:00:00Z", "updated_at": "2000-01-01T00:00:00Z"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["created_at"] != "2000-01-01T00:00:00Z"
        assert response.json()["updated_at"] != "2000-01-01T00:00:00Z"

    def test_create_id_is_read_only(self):
        response = self.client.post(self._url(), data={"id": "00000000-0000-0000-0000-000000000000"}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] != "00000000-0000-0000-0000-000000000000"

    def test_create_updates_updated_at(self):
        seed = self._seed_config()

        response = self.client.post(self._url(), data={"mode": "dry_run"}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["updated_at"] >= seed["updated_at"]

    # -- Validation --

    def test_rejects_invalid_filter_tree(self):
        response = self.client.post(
            self._url(),
            data={"filter_tree": {"type": "condition", "field": "bad_field", "operator": "exact", "value": "x"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert data["type"] == "validation_error"
        assert data["attr"] == "filter_tree__filter_tree"
        assert "field must be one of" in data["detail"]

    def test_rejects_invalid_test_cases(self):
        response = self.client.post(
            self._url(),
            data={"test_cases": [{"expected_result": "maybe"}]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert data["type"] == "validation_error"
        assert data["attr"] == "test_cases__test_cases"
        assert "must be 'drop' or 'ingest'" in data["detail"]

    def test_rejects_invalid_mode(self):
        response = self.client.post(self._url(), data={"mode": "turbo"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert data["type"] == "validation_error"
        assert data["attr"] == "mode"

    def test_rejects_failing_test_cases(self):
        response = self.client.post(
            self._url(),
            data={
                "filter_tree": _cond("event_name", "exact", "$pageview"),
                "test_cases": [{"event_name": "$pageview", "expected_result": "ingest"}],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert data["type"] == "validation_error"
        assert "expected 'ingest' but got 'drop'" in data["detail"]

    def test_rejected_request_does_not_persist(self):
        seed = self._seed_config()

        response = self.client.post(
            self._url(),
            data={"mode": "turbo"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        config = EventFilterConfig.objects.get(team=self.team)
        assert config.mode == seed["mode"]
        assert config.filter_tree == seed["filter_tree"]

    # -- Disallowed methods --

    @parameterized.expand(["put", "patch", "delete"])
    def test_disallowed_method(self, method: str):
        response = getattr(self.client, method)(self._url(), data={"mode": "live"}, format="json")
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # -- Metrics --

    @patch("posthog.api.event_filter_config.fetch_app_metrics_trends")
    def test_metrics_returns_empty_when_no_config(self, mock_fetch):
        response = self.client.get(self._url() + "metrics/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"labels": [], "series": []}
        mock_fetch.assert_not_called()
        assert not EventFilterConfig.objects.filter(team=self.team).exists()

    @patch("posthog.api.event_filter_config.fetch_app_metric_totals")
    def test_metrics_totals_returns_empty_when_no_config(self, mock_fetch):
        response = self.client.get(self._url() + "metrics/totals/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"totals": {}}
        mock_fetch.assert_not_called()
        assert not EventFilterConfig.objects.filter(team=self.team).exists()

    @patch("posthog.api.event_filter_config.fetch_app_metrics_trends")
    def test_metrics_calls_clickhouse_when_config_exists(self, mock_fetch):
        from posthog.api.app_metrics2 import AppMetricsResponse

        mock_fetch.return_value = AppMetricsResponse(labels=["2026-04-01"], series=[])
        self._seed_config()

        response = self.client.get(self._url() + "metrics/")

        assert response.status_code == status.HTTP_200_OK
        mock_fetch.assert_called_once()
        assert mock_fetch.call_args.kwargs["app_source"] == "event_filter"

    @patch("posthog.api.event_filter_config.fetch_app_metric_totals")
    def test_metrics_totals_calls_clickhouse_when_config_exists(self, mock_fetch):
        from posthog.api.app_metrics2 import AppMetricsTotalsResponse

        mock_fetch.return_value = AppMetricsTotalsResponse(totals={"success": 10})
        self._seed_config()

        response = self.client.get(self._url() + "metrics/totals/")

        assert response.status_code == status.HTTP_200_OK
        mock_fetch.assert_called_once()
        assert response.json() == {"totals": {"success": 10}}

    # -- Complex end-to-end --

    def test_complex_filter_tree_with_test_cases(self):
        # Drop: ($autocapture OR event contains "bot_") AND NOT distinct_id is "admin"
        tree = _and(
            _or(
                _cond("event_name", "exact", "$autocapture"),
                _cond("event_name", "contains", "bot_"),
            ),
            _not(_cond("distinct_id", "exact", "admin")),
        )
        test_cases = [
            {"event_name": "$autocapture", "distinct_id": "user-1", "expected_result": "drop"},
            {"event_name": "bot_heartbeat", "distinct_id": "user-2", "expected_result": "drop"},
            {"event_name": "$autocapture", "distinct_id": "admin", "expected_result": "ingest"},
            {"event_name": "purchase", "distinct_id": "user-1", "expected_result": "ingest"},
        ]

        response = self.client.post(
            self._url(),
            data={"mode": "live", "filter_tree": tree, "test_cases": test_cases},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["mode"] == "live"
        assert data["filter_tree"] == tree
        assert data["test_cases"] == test_cases

        # Flip one test case expectation — should fail validation
        bad_test_cases = [{"event_name": "$autocapture", "distinct_id": "user-1", "expected_result": "ingest"}]
        response = self.client.post(
            self._url(),
            data={"test_cases": bad_test_cases},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "expected 'ingest' but got 'drop'" in response.json()["detail"]

        # Verify original config unchanged
        config = EventFilterConfig.objects.get(team=self.team)
        assert config.test_cases == test_cases

    # -- Multi-tenancy --

    def test_list_returns_only_own_teams_config(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        EventFilterConfig.objects.create(team=self.team, mode=EventFilterMode.LIVE, filter_tree=_cond())
        EventFilterConfig.objects.create(
            team=other_team, mode=EventFilterMode.DRY_RUN, filter_tree=_cond("distinct_id", "contains", "bot")
        )

        response = self.client.get(self._url(self.team.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["mode"] == "live"

        response = self.client.get(self._url(other_team.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["mode"] == "dry_run"

    def test_create_does_not_modify_other_teams_config(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        EventFilterConfig.objects.create(team=other_team, mode=EventFilterMode.DISABLED)

        self.client.post(self._url(self.team.id), data={"mode": "live", "filter_tree": _cond()}, format="json")

        other_config = EventFilterConfig.objects.get(team=other_team)
        assert other_config.mode == EventFilterMode.DISABLED

    def test_cannot_access_config_from_other_organization(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Org Team")

        response = self.client.get(self._url(other_team.id))

        assert response.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]

    def test_create_scoped_to_team(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        self.client.post(self._url(self.team.id), data={"mode": "disabled"}, format="json")
        self.client.post(self._url(other_team.id), data={"mode": "disabled"}, format="json")

        assert EventFilterConfig.objects.filter(team=self.team).count() == 1
        assert EventFilterConfig.objects.filter(team=other_team).count() == 1
        assert EventFilterConfig.objects.count() == 2

    # -- Auth --

    def test_unauthenticated_request_is_rejected(self):
        self.client.logout()

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
