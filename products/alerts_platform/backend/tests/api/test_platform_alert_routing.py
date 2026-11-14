from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade.api import has_incident_destination
from products.alerts_platform.backend.facade.contracts import ROUTING_FLAG, SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.logic.alert_routes import routed_receivers
from products.alerts_platform.backend.models import AlertReceiver, PlatformAlertConfiguration
from products.alerts_platform.backend.presentation.views.platform_alert import SOURCE_KIND_RESOURCE

_WEBHOOK = {"type": "webhook", "webhook_url": "https://example.com/hooks/secret-token"}
_PAGERDUTY = {
    "type": "pagerduty",
    "pagerduty_routing_key": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
    "pagerduty_severity": "warning",
}
_INCIDENT_IO = {
    "type": "incident_io",
    "incident_io_alert_source_config_id": "01GW2G3V0S59R238FAHPDS1R66",
    "incident_io_secret": "not-a-real-secret-c3d4",
}
_SECRET_FIELD = {"pagerduty": "pagerduty_routing_key", "incident_io": "incident_io_secret"}
# Built from the source list, so a key in this test keeps covering every source when a new one is added.
_EVERY_SOURCE_WRITE_SCOPES = [
    "alert:write",
    "insight:write",
    *sorted({f"{resource}:write" for resource in SOURCE_KIND_RESOURCE.values()}),
]

_EVERY_SOURCE_READ_SCOPES = [scope.replace(":write", ":read") for scope in _EVERY_SOURCE_WRITE_SCOPES]


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

        previewed = self.client.post(
            f"{self.routes_url}matching/", {"labels": {"team": "apm", "severity": "critical"}}, format="json"
        )
        assert previewed.status_code == status.HTTP_200_OK, previewed.json()
        assert [(m["route"]["id"], m["receiver"]["id"], m["receiver"]["webhook_url"]) for m in previewed.json()] == [
            (route.json()["id"], receiver["id"], "https://example.com")
        ]
        assert (
            self.client.post(f"{self.routes_url}matching/", {"labels": {"team": "checkout"}}, format="json").json()
            == []
        )

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
            ("pagerduty_matching_route", _PAGERDUTY, True, "apm", True),
            ("pagerduty_route_matches_another_team", _PAGERDUTY, True, "web", False),
            ("pagerduty_routing_off_for_the_team", _PAGERDUTY, False, "apm", False),
            # A dropped resolve would leave the incident open for good, so a failed lookup keeps the actions.
            ("pagerduty_flag_lookup_fails", _PAGERDUTY, RuntimeError("flags down"), "apm", True),
            ("incident_io_matching_route", _INCIDENT_IO, True, "apm", True),
        ]
    )
    def test_an_incident_receiver_makes_the_alerts_its_routes_match_open_and_close_incidents(
        self, _name: str, body: dict[str, str], routing_on: bool | Exception, alert_team: str, expected: bool
    ) -> None:
        def feature_enabled(flag: str, *args: Any, **kwargs: Any) -> bool:
            if isinstance(routing_on, Exception):
                raise routing_on
            return routing_on and flag == ROUTING_FLAG

        receiver = self.client.post(self.receivers_url, {"name": "Pager", **body}, format="json").json()
        self.client.post(
            self.routes_url,
            {"receiver_id": receiver["id"], "matchers": [{"label": "team", "value": "apm"}]},
            format="json",
        )
        with team_scope(self.team.id):
            configuration = PlatformAlertConfiguration.objects.for_team(self.team.id).create(
                team=self.team,
                name="API errors",
                source_kind=SourceKind.LOGS,
                check_interval_minutes=5,
                destinations_owner=PlatformAlertOwner.PLATFORM,
                labels={"team": alert_team},
            )
            with patch(
                "products.alerts_platform.backend.delivery.team_flags.posthoganalytics.feature_enabled",
                side_effect=feature_enabled,
            ):
                follows = has_incident_destination(team_id=self.team.id, configuration_id=configuration.id)

        assert follows is expected
        # Reads keep the last four characters of the credential, enough to tell two apart.
        [listed] = self.client.get(self.receivers_url).json()
        assert {key: listed[key] for key in body} == {**body, _SECRET_FIELD[body["type"]]: "••••c3d4"}

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

    @parameterized.expand(
        [
            ("member_who_is_not_an_org_admin", None),
            ("key_with_every_source_read_scope", _EVERY_SOURCE_READ_SCOPES),
        ]
    )
    def test_previewing_routing_is_a_read(self, _name: str, key_scopes: list[str] | None) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        if key_scopes is not None:
            self.client.logout()
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.create_personal_api_key_with_scopes(key_scopes)}")

        previewed = self.client.post(f"{self.routes_url}matching/", {"labels": {"team": "apm"}}, format="json")

        assert previewed.status_code == status.HTTP_200_OK, previewed.json()

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
            ("email_is_not_routable", {"name": "Mail", "type": "email"}, "type"),
            (
                "pagerduty_key_is_not_an_integration_key",
                {"name": "Pager", "type": "pagerduty", "pagerduty_routing_key": "not-a-key"},
                "pagerduty_routing_key",
            ),
            (
                "incident_io_id_is_not_an_alert_source_id",
                {
                    **_INCIDENT_IO,
                    "name": "Incidents",
                    "incident_io_alert_source_config_id": "../../01GW2G3V0S59R238FAHPDS1R66",
                },
                "incident_io_alert_source_config_id",
            ),
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
