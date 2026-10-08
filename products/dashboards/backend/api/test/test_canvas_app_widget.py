from typing import Any
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.scoping import team_scope
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.canvas.backend.facade.testing import create_canvas
from products.dashboards.backend.widget_registry import CANVAS_APP_WIDGET_TYPE, validate_widget_config
from products.dashboards.backend.widgets.canvas_app import run_canvas_app_widget
from products.tasks.backend.models import Channel


def _block_canvas_for_member(team: Team, canvas_id: UUID, member: User) -> None:
    from products.access_control.backend.models.access_control import AccessControl  # noqa: PLC0415

    team.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"}]
    team.organization.save()
    membership = OrganizationMembership.objects.get(organization=team.organization, user=member)
    AccessControl.objects.create(
        team=team,
        resource="canvas",
        resource_id=str(canvas_id),
        organization_member=membership,
        access_level="none",
    )
    cache.clear()


class TestCanvasAppWidgetConfig(APIBaseTest):
    def test_config_defaults_to_unconfigured(self) -> None:
        validated = validate_widget_config(CANVAS_APP_WIDGET_TYPE, {})
        assert validated.get("canvasId") is None

    def test_canvas_id_round_trips_as_a_string(self) -> None:
        canvas_id = uuid4()
        validated = validate_widget_config(CANVAS_APP_WIDGET_TYPE, {"canvasId": str(canvas_id)})
        assert validated["canvasId"] == str(canvas_id)

    @parameterized.expand(
        [
            ("unknown_key", {"evil": True}),
            ("not_a_uuid", {"canvasId": "not-a-uuid"}),
            ("date_range_is_not_supported", {"dateRange": {"date_from": "-7d"}}),
        ]
    )
    def test_rejects_invalid_config(self, _name: str, config: dict[str, Any]) -> None:
        from rest_framework.exceptions import ValidationError  # noqa: PLC0415

        with self.assertRaises(ValidationError):
            validate_widget_config(CANVAS_APP_WIDGET_TYPE, config)


class CanvasAppWidgetBaseTest(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        with team_scope(self.team.id):
            self.channel = Channel.objects.create(team=self.team, name="general", created_by=self.user)

    def _create_canvas(self, *, name: str = "Launch board", channel: Channel | None = None) -> UUID:
        return create_canvas(
            team_id=self.team.id,
            channel_id=(channel or self.channel).id,
            name=name,
            created_by_id=self.user.id,
        )


class TestCanvasAppWidgetRunner(CanvasAppWidgetBaseTest):
    def test_returns_needs_configuration_when_no_canvas_selected(self) -> None:
        result = run_canvas_app_widget(self.team, {}, user=self.user)

        assert result == {"canvas": None, "needsConfiguration": True}

    def test_returns_not_found_for_missing_canvas(self) -> None:
        result = run_canvas_app_widget(self.team, {"canvasId": str(uuid4())}, user=self.user)

        assert result == {"canvas": None, "canvasNotFound": True}

    def test_returns_not_found_for_other_team_canvas(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        with team_scope(other_team.id):
            other_channel = Channel.objects.create(team=other_team, name="general", created_by=self.user)
        canvas_id = create_canvas(
            team_id=other_team.id, channel_id=other_channel.id, name="Other", created_by_id=self.user.id
        )

        result = run_canvas_app_widget(self.team, {"canvasId": str(canvas_id)}, user=self.user)

        assert result == {"canvas": None, "canvasNotFound": True}

    def test_returns_not_found_for_canvas_in_another_members_personal_space(self) -> None:
        owner = User.objects.create_and_join(self.organization, "owner@example.test", "pw")
        with team_scope(self.team.id):
            personal = Channel.objects.create(
                team=self.team,
                name=Channel.PERSONAL_CHANNEL_NAME,
                channel_type=Channel.ChannelType.PERSONAL,
                created_by=owner,
            )
        canvas_id = create_canvas(team_id=self.team.id, channel_id=personal.id, name="Mine", created_by_id=owner.id)

        result = run_canvas_app_widget(self.team, {"canvasId": str(canvas_id)}, user=self.user)

        assert result == {"canvas": None, "canvasNotFound": True}

    def test_returns_not_found_for_canvas_the_user_cannot_access(self) -> None:
        canvas_id = self._create_canvas()
        member = User.objects.create_and_join(self.organization, "member@example.test", "pw")
        _block_canvas_for_member(self.team, canvas_id, member)

        result = run_canvas_app_widget(self.team, {"canvasId": str(canvas_id)}, user=member)

        assert result == {"canvas": None, "canvasNotFound": True}

    def test_returns_the_canvas_summary_for_a_visible_canvas(self) -> None:
        canvas_id = self._create_canvas(name="Launch board")

        result = run_canvas_app_widget(self.team, {"canvasId": str(canvas_id)}, user=self.user)

        assert result == {
            "canvas": {
                "id": str(canvas_id),
                "name": "Launch board",
                "spaceId": str(self.channel.id),
                "publishedBuildId": None,
                "currentVersionId": None,
            }
        }


class TestCanvasAppWidgetApi(CanvasAppWidgetBaseTest):
    _FLAG_PATCH_TARGETS = (
        "products.dashboards.backend.api.dashboard.dashboard_widgets_enabled",
        "products.dashboards.backend.widget_create.dashboard_widgets_enabled",
    )

    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        for target in self._FLAG_PATCH_TARGETS:
            patcher = patch(target, return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    @patch("products.dashboards.backend.widget_create.widget_flag_enabled", return_value=False)
    def test_adding_a_canvas_app_tile_requires_the_small_software_apps_flag(self, flag_enabled) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [{"widget": {"widget_type": CANVAS_APP_WIDGET_TYPE, "config": {}}}]},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "Canvas app widgets are not enabled" in str(response.json())
        flag_enabled.assert_called_once()
        assert flag_enabled.call_args.args[0] == "small-software-apps"

    @patch("products.dashboards.backend.widget_create.widget_flag_enabled", return_value=True)
    def test_run_widgets_requires_canvas_read_scope_on_a_personal_api_key(self, _flag_enabled) -> None:
        canvas_id = self._create_canvas()
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id, widget_type="canvas_app", config={"canvasId": str(canvas_id)}
        )
        tile_id = dashboard_json["tiles"][0]["id"]
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="dashboard only",
            user=self.user,
            secure_value=hash_key_value(token),
            scopes=["dashboard:read"],
            scoped_teams=[],
            scoped_organizations=[],
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/run_widgets/",
            {"tile_ids": str(tile_id)},
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0]["error"] == "API key missing required scope 'canvas:read'"
