from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.integration import Integration
from posthog.models.integration.auth_types import ANY
from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import create_configuration, list_alert_destinations
from products.alerts_platform.backend.facade.contracts import Grouping, PlatformAlertConfigurationEdit, SourceKind
from products.alerts_platform.backend.models import PlatformAlertConfiguration

_ROUTING_KEY = "0123456789abcdef0123456789abcdef"


class TestPlatformAlertDestinations(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True))
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))
        # Metrics is a kind the platform creates natively, with `AlertDestination` rows from the start.
        with team_scope(self.team.id):
            self.configuration_id = create_configuration(
                team_id=self.team.id,
                source_kind=SourceKind.METRICS,
                edit=PlatformAlertConfigurationEdit(
                    name="Consumer lag",
                    enabled=True,
                    source_config={"query": "sum(lag)", "condition": {"operator": "gt", "threshold": 1000}},
                    grouping=Grouping(),
                    schedule_restriction=None,
                    evaluation_periods=1,
                    datapoints_to_alarm=1,
                    cooldown_minutes=0,
                ),
                created_by_id=self.user.id,
            ).id
        self.url = f"/api/projects/{self.team.id}/platform_alerts/{self.configuration_id}/destinations/"

    def test_destinations_are_alert_destination_rows_that_go_with_the_alert(self) -> None:
        workspace = Integration.objects.create(team=self.team, kind="slack", config={}, sensitive_config={})
        slack = self.client.post(
            self.url,
            {
                "type": "slack",
                "slack_workspace_id": workspace.id,
                "slack_channel_id": "C123",
                "webhook_url": "https://example.com/hooks/secret-token",
            },
            format="json",
        )
        with self.captureOnCommitCallbacks(execute=True):
            pagerduty = self.client.post(
                self.url, {"type": "pagerduty", "pagerduty_routing_key": _ROUTING_KEY}, format="json"
            )

        assert slack.status_code == pagerduty.status_code == status.HTTP_201_CREATED, (slack.json(), pagerduty.json())
        assert (slack.json()["event_kinds"], pagerduty.json()["event_kinds"]) == (
            ["firing", "resolved", "errored", "broken"],
            ["firing", "resolved"],
        )
        listed = self.client.get(self.url).json()
        assert [d["id"] for d in listed] == [slack.json()["id"], pagerduty.json()["id"]]
        assert listed[1]["pagerduty_routing_key"] == "••••cdef"
        with team_scope(self.team.id):
            stored = list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration_id)
        assert [sorted(d.data) for d in stored] == [
            ["slack_channel_id", "slack_workspace_id", "type"],
            ["pagerduty_region", "pagerduty_routing_key", "pagerduty_severity", "type"],
        ]

        removed = self.client.post(f"{self.url}delete/", {"destination_ids": [slack.json()["id"]]}, format="json")
        assert removed.status_code == status.HTTP_204_NO_CONTENT
        assert [d["type"] for d in self.client.get(self.url).json()] == ["pagerduty"]
        logged = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="PlatformAlertConfiguration",
            item_id=str(self.configuration_id),
            detail__changes__contains=[{"field": "destinations"}],
        ).order_by("created_at")
        assert [
            (
                row.user_id,
                [(change["action"], change["before"] or change["after"]) for change in (row.detail or {})["changes"]],
            )
            for row in logged
        ] == [
            (self.user.id, [("created", {"id": slack.json()["id"], "type": "slack"})]),
            (self.user.id, [("created", {"id": pagerduty.json()["id"], "type": "pagerduty"})]),
            (self.user.id, [("deleted", {"id": slack.json()["id"], "type": "slack"})]),
        ]
        assert not any(_ROUTING_KEY in str(row.detail) or "secret-token" in str(row.detail) for row in logged)
        deleted = self.client.delete(f"/api/projects/{self.team.id}/platform_alerts/{self.configuration_id}/")
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        with team_scope(self.team.id):
            assert list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration_id) == ()

    @parameterized.expand(
        [
            # The alert is hidden from a caller who cannot read its product.
            ("read_alert_only", "get", ["alert:read"], status.HTTP_404_NOT_FOUND),
            ("read_metrics_only", "get", ["metrics:read"], status.HTTP_403_FORBIDDEN),
            ("read_both", "get", ["alert:read", "metrics:read"], status.HTTP_200_OK),
            ("write_with_read_scopes", "post", ["alert:read", "metrics:read"], status.HTTP_403_FORBIDDEN),
            ("write_alert_without_metrics", "post", ["alert:write", "metrics:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_destinations_need_the_alert_and_the_kinds_scope(
        self, _name: str, method: str, scopes: list[str], expected: int
    ) -> None:
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.create_personal_api_key_with_scopes(scopes)}")

        if method == "get":
            response = self.client.get(self.url)
        else:
            response = self.client.post(
                self.url, {"type": "pagerduty", "pagerduty_routing_key": _ROUTING_KEY}, format="json"
            )

        assert response.status_code == expected, response.json()

    @parameterized.expand(
        [
            ("http_webhook", {"type": "webhook", "webhook_url": "http://example.com/alerts"}, "webhook_url"),
            ("teams_url_not_from_teams", {"type": "teams", "webhook_url": "https://example.com/alerts"}, "webhook_url"),
            (
                "unconnected_slack_workspace",
                {"type": "slack", "slack_workspace_id": 999999, "slack_channel_id": "C123"},
                "slack_workspace_id",
            ),
            ("short_pagerduty_key", {"type": "pagerduty", "pagerduty_routing_key": "abc"}, "pagerduty_routing_key"),
            ("email", {"type": "email"}, "type"),
            ("slack_without_workspace", {"type": "slack", "slack_channel_id": "C123"}, "slack_workspace_id"),
        ]
    )
    def test_a_destination_that_could_never_deliver_is_refused(
        self, _name: str, body: dict[str, object], field: str
    ) -> None:
        response = self.client.post(self.url, body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == field

    def test_a_slack_workspace_delivery_cannot_send_through_is_refused(self) -> None:
        # Delivery sends only through an OAuth Slack integration, so a token one would never notify.
        workspace = Integration.objects._with_auth(ANY).create(
            team=self.team, kind="slack", config={"auth_type": "token"}, sensitive_config={}
        )

        response = self.client.post(
            self.url,
            {"type": "slack", "slack_workspace_id": workspace.id, "slack_channel_id": "C123"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "slack_workspace_id"

    def test_a_pagerduty_destination_with_an_open_incident_cannot_be_removed(self) -> None:
        created = self.client.post(
            self.url, {"type": "pagerduty", "pagerduty_routing_key": _ROUTING_KEY}, format="json"
        ).json()
        with team_scope(self.team.id):
            platform_testing.start_firing(
                self.configuration_id, team_id=self.team.id, at=datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
            )

        refused = self.client.post(f"{self.url}delete/", {"destination_ids": [created["id"]]}, format="json")
        assert refused.status_code == status.HTTP_409_CONFLICT, refused.json()
        assert [d["id"] for d in self.client.get(self.url).json()] == [created["id"]]

    def test_a_webhook_secret_is_never_listed(self) -> None:
        created = self.client.post(
            self.url,
            {"type": "discord", "webhook_url": "https://discord.com/api/webhooks/123/secret-token"},
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.json()

        assert [d["webhook_url"] for d in self.client.get(self.url).json()] == ["https://discord.com"]

    @parameterized.expand([("duplicate", 1, 0), ("over_the_cap", 5, 5)])
    def test_a_destination_past_the_alerts_limits_is_refused(self, _name: str, existing: int, next_index: int) -> None:
        def discord(index: int) -> dict[str, str]:
            return {"type": "discord", "webhook_url": f"https://discord.com/api/webhooks/{index}/token"}

        for index in range(existing):
            assert self.client.post(self.url, discord(index), format="json").status_code == status.HTTP_201_CREATED

        response = self.client.post(self.url, discord(next_index), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_a_kind_whose_product_owns_its_destinations_is_refused(self) -> None:
        with team_scope(self.team.id):
            logs_alert = PlatformAlertConfiguration.objects.create(
                team=self.team,
                name="API errors",
                source_kind=PlatformAlertConfiguration.SourceKind.LOGS,
                source_config={
                    "filters": {"serviceNames": ["api"]},
                    "condition": {"threshold_count": 1, "threshold_operator": "above", "window_minutes": 5},
                },
                check_interval_minutes=10,
                owner=PlatformAlertConfiguration.Owner.PLATFORM,
            )

        response = self.client.get(f"/api/projects/{self.team.id}/platform_alerts/{logs_alert.id}/destinations/")

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()
