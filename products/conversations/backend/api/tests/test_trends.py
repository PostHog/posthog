from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team
from posthog.models.scoping import team_scope

from products.conversations.backend.models import IncidentScope, IncidentStatus, TicketAlertRule, TicketIncident
from products.conversations.backend.models.ticket_alert_rule import MAX_ENABLED_RULES_PER_TEAM


class TestTicketAlertRuleAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/conversations/alert_rules/"

    def _valid_payload(self, **overrides) -> dict:
        payload = {
            "name": "Billing complaints",
            "filters": {"channel_source": "email"},
            "window_minutes": 120,
            "min_count": 5,
        }
        payload.update(overrides)
        return payload

    @patch("products.conversations.backend.api.trends.report_user_action")
    def test_create_rule(self, _mock_report):
        response = self.client.post(self.base_url, self._valid_payload(), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["name"] == "Billing complaints"
        assert data["filters"] == {"channel_source": "email"}
        assert data["created_by"]["id"] == self.user.pk

    def test_rejects_time_filter_keys(self):
        # date_from would fight the rule's own window; the serializer must reject it.
        response = self.client.post(self.base_url, self._valid_payload(filters={"date_from": "-7d"}), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_unknown_filter_keys(self):
        response = self.client.post(self.base_url, self._valid_payload(filters={"not_a_filter": "x"}), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_search_filter(self):
        # search runs an unindexed comment scan; fine interactively, not on a
        # recurring background evaluation.
        response = self.client.post(self.base_url, self._valid_payload(filters={"search": "csv export"}), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand(
        [
            ("bad_status", {"status": "not_a_status"}),
            ("bad_channel", {"channel_source": "carrier_pigeon"}),
            ("tags_not_json", {"tags": "billing"}),
            ("tags_too_many", {"tags_all": '["t0","t1","t2","t3","t4","t5","t6","t7","t8","t9","t10"]'}),
            ("bad_assignee", {"assignee": "user:not-a-number"}),
        ]
    )
    def test_rejects_malformed_filter_values(self, _name, filters):
        # A malformed value would evaluate as "no filter", silently broadening the
        # rule to all tickets; it must be rejected at save time.
        response = self.client.post(self.base_url, self._valid_payload(filters=filters), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_put_is_not_allowed(self):
        # Full PUT would reset omitted fields (filters defaults to {}), silently
        # clearing saved criteria — the viewset is PATCH-only like TicketViewViewSet.
        with team_scope(self.team.id):
            rule = TicketAlertRule.objects.create(team=self.team, name="Rule", filters={"channel_source": "email"})
        response = self.client.put(f"{self.base_url}{rule.id}/", self._valid_payload(), format="json")
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_enabled_rule_cap_enforced(self):
        with team_scope(self.team.id):
            for i in range(MAX_ENABLED_RULES_PER_TEAM):
                TicketAlertRule.objects.create(team=self.team, name=f"Rule {i}", enabled=True)
        response = self.client.post(self.base_url, self._valid_payload(), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "enabled"

    def test_list_is_team_scoped(self):
        other = Team.objects.create(organization=self.organization, name="Other")
        with team_scope(self.team.id):
            TicketAlertRule.objects.create(team=self.team, name="Mine")
        with team_scope(other.id):
            TicketAlertRule.objects.create(team=other, name="Theirs")
        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        names = {row["name"] for row in response.json()["results"]}
        assert names == {"Mine"}


class TestTicketIncidentAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/conversations/incidents/"

    def _make_incident(self, **overrides) -> TicketIncident:
        defaults = {
            "team": self.team,
            "scope": IncidentScope.VOLUME,
            "status": IncidentStatus.ACTIVE,
            "detected_at": timezone.now(),
            "window_minutes": 120,
            "observed_count": 12,
        }
        defaults.update(overrides)
        with team_scope(self.team.id):
            return TicketIncident.objects.create(**defaults)

    def test_list_filters_by_status(self):
        self._make_incident()
        self._make_incident(status=IncidentStatus.RESOLVED, scope=IncidentScope.CHANNEL, dimension_value="email")
        response = self.client.get(self.base_url, {"status": "active"})
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["status"] == "active"

    @patch("products.conversations.backend.api.trends.report_user_action")
    def test_dismiss_active_incident(self, _mock_report):
        incident = self._make_incident()
        response = self.client.post(f"{self.base_url}{incident.id}/dismiss/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "dismissed"
        incident.refresh_from_db()
        assert incident.status == IncidentStatus.DISMISSED

    @patch("products.conversations.backend.api.trends.report_user_action")
    def test_dismiss_resolved_incident_is_noop(self, _mock_report):
        incident = self._make_incident(status=IncidentStatus.RESOLVED)
        response = self.client.post(f"{self.base_url}{incident.id}/dismiss/")
        assert response.status_code == status.HTTP_200_OK
        incident.refresh_from_db()
        assert incident.status == IncidentStatus.RESOLVED
