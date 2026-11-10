from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping import team_scope

from products.alerts_platform.backend.logic.alert_routes import routed_receivers
from products.alerts_platform.backend.models import AlertReceiver
from products.alerts_platform.backend.presentation.views.platform_alert import SOURCE_KIND_RESOURCE

_WEBHOOK = {"type": "webhook", "webhook_url": "https://example.com/hooks/secret-token"}
# Built from the source list, so a key in this test keeps covering every source when a new one is added.
_EVERY_SOURCE_WRITE_SCOPES = [
    "alert:write",
    "insight:write",
    *sorted({f"{resource}:write" for resource in SOURCE_KIND_RESOURCE.values()}),
]


class TestPlatformAlertRouting(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag_patch = self.enterContext(
            patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
        )
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.receivers_url = f"/api/projects/{self.team.id}/platform_alert_receivers/"
        self.routes_url = f"/api/projects/{self.team.id}/platform_alert_routes/"

    def _receiver(self, **fields: Any) -> dict[str, Any]:
        response = self.client.post(self.receivers_url, {"name": "Infra", **_WEBHOOK, **fields}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    def test_routes_written_here_are_the_routes_delivery_matches(self) -> None:
        receiver = self._receiver()
        route = self.client.post(
            self.routes_url,
            {
                "receiver_id": receiver["id"],
                "matchers": [{"label": "team", "value": "apm"}],
                "event_kinds": ["firing", "resolved"],
            },
            format="json",
        )
        assert route.status_code == status.HTTP_201_CREATED, route.json()

        with team_scope(self.team.id):
            matched = routed_receivers(team_id=self.team.id, labels={"team": "apm", "severity": "critical"})
            unmatched = routed_receivers(team_id=self.team.id, labels={"team": "checkout"})
        assert [(str(r.id), r.data["webhook_url"], [k.value for k in r.event_kinds]) for r in matched] == [
            (receiver["id"], _WEBHOOK["webhook_url"], ["firing", "resolved"])
        ]
        assert unmatched == ()

        listed = self.client.get(self.receivers_url).json()
        assert [(r["name"], r["webhook_url"], r["route_count"]) for r in listed] == [
            ("Infra", "https://example.com", 1)
        ]

    def test_edits_reach_delivery_and_deleting_a_receiver_removes_its_routes(self) -> None:
        receiver = self._receiver()
        route = self.client.post(self.routes_url, {"receiver_id": receiver["id"]}, format="json").json()

        narrowed = self.client.patch(
            f"{self.routes_url}{route['id']}/", {"matchers": [{"label": "team", "value": "apm"}]}, format="json"
        )
        assert narrowed.status_code == status.HTTP_200_OK, narrowed.json()
        with team_scope(self.team.id):
            assert [str(r.id) for r in routed_receivers(team_id=self.team.id, labels={"team": "apm"})] == [
                receiver["id"]
            ]
            assert routed_receivers(team_id=self.team.id, labels={"team": "web"}) == ()
        disabled = self.client.patch(f"{self.routes_url}{route['id']}/", {"enabled": False}, format="json")
        assert disabled.status_code == status.HTTP_200_OK, disabled.json()
        with team_scope(self.team.id):
            assert routed_receivers(team_id=self.team.id, labels={"team": "apm"}) == ()

        renamed = self.client.patch(f"{self.receivers_url}{receiver['id']}/", {"name": "Infra pager"}, format="json")
        assert renamed.status_code == status.HTTP_200_OK, renamed.json()
        with team_scope(self.team.id):
            assert AlertReceiver.objects.for_team(self.team.id).get(id=receiver["id"]).config == _WEBHOOK

        deleted = self.client.delete(f"{self.receivers_url}{receiver['id']}/")
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert self.client.get(self.routes_url).json() == []

    @parameterized.expand(
        [
            ("routing_flag_off", None, False, status.HTTP_403_FORBIDDEN),
            ("member_who_is_not_an_org_admin", None, True, status.HTTP_403_FORBIDDEN),
            ("key_without_source_scopes", ["alert:read", "alert:write"], True, status.HTTP_403_FORBIDDEN),
            ("key_with_every_source_scope", _EVERY_SOURCE_WRITE_SCOPES, True, status.HTTP_201_CREATED),
        ]
    )
    def test_writing_routing_needs_the_flag_an_org_admin_and_every_source(
        self, _name: str, key_scopes: list[str] | None, flag_on: bool, expected: int
    ) -> None:
        if _name == "member_who_is_not_an_org_admin":
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()
        if not flag_on:
            self.flag_patch.side_effect = lambda flag, *args, **kwargs: flag != "platform-alerts-routing"
        if key_scopes is not None:
            self.client.logout()
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.create_personal_api_key_with_scopes(key_scopes)}")

        response = self.client.post(self.receivers_url, {"name": "Infra", **_WEBHOOK}, format="json")

        assert response.status_code == expected, response.json()

    def test_a_route_cannot_send_to_another_projects_receiver(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        with team_scope(other_team.id):
            foreign = AlertReceiver.objects.for_team(other_team.id).create(
                team_id=other_team.id, name="Theirs", type="webhook", config=_WEBHOOK
            )

        response = self.client.post(self.routes_url, {"receiver_id": str(foreign.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "receiver_id"

    @parameterized.expand(
        [
            ("same_label_twice", [{"label": "team", "value": "a"}, {"label": "team", "value": "b"}]),
            ("invalid_label_name", [{"label": "team-name", "value": "a"}]),
            ("reserved_label", [{"label": "alertname", "value": "a"}]),
            ("blank_value", [{"label": "team", "value": " "}]),
        ]
    )
    def test_refuses_matchers_no_alert_label_can_satisfy(self, _name: str, matchers: list[dict[str, str]]) -> None:
        receiver = self._receiver()

        response = self.client.post(
            self.routes_url, {"receiver_id": receiver["id"], "matchers": matchers}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "matchers"

    @parameterized.expand(
        [
            ("pagerduty_is_not_routable", {"name": "Pager", "type": "pagerduty"}, "type"),
            ("duplicate_name", {"name": "Infra", **_WEBHOOK}, "name"),
            ("slack_workspace_of_no_integration", {"name": "Chat", "type": "slack"}, "slack_workspace_id"),
        ]
    )
    def test_refuses_receivers_delivery_cannot_send_to(self, _name: str, body: dict[str, Any], attr: str) -> None:
        self._receiver()
        if body.get("type") == "slack":
            body = {**body, "slack_workspace_id": 999999, "slack_channel_id": "C1"}

        response = self.client.post(self.receivers_url, body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == attr

    def test_slack_receiver_needs_a_workspace_connected_to_the_project(self) -> None:
        workspace = Integration.objects.create(team=self.team, kind="slack", config={}, sensitive_config={})

        response = self.client.post(
            self.receivers_url,
            {"name": "Chat", "type": "slack", "slack_workspace_id": workspace.id, "slack_channel_id": "C1"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
