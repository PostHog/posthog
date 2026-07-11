import json
from datetime import timedelta
from functools import wraps
from urllib.parse import quote

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, Mock, patch

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.utils import timezone
from django.utils.timezone import now

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import PermissionDenied

from posthog.api.sharing import (
    SHARING_RESOURCE_EDIT_CHECKS,
    _assert_every_shareable_resource_is_gated,
    _log_share_password_attempt,
    check_can_edit_sharing_configuration,
    shared_url_as_png,
)
from posthog.constants import AvailableFeature
from posthog.models import ActivityLog, OrganizationMembership
from posthog.models.filters.filter import Filter
from posthog.models.share_password import SharePassword
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.user import User

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.dashboards.backend.models.dashboard_widget import DashboardWidget
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.exports.backend.models.exported_asset import ExportedAsset, get_render_access_token
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.models.insight import Insight

from ee.models.rbac.access_control import AccessControl


def mock_exporter_template(test_func):
    """
    Decorator to mock render_template for sharing tests.

    This provides a simplified version of the exporter template that always includes
    the exported_data in both window.POSTHOG_EXPORTED_DATA and the response body,
    simulating what the actual built exporter.html template would do.
    """

    @wraps(test_func)
    @patch("posthog.api.sharing.render_template")
    def wrapper(self, mock_render_template, *args, **kwargs):
        def mock_render_side_effect(template_name, request, context, **kwargs):
            from django.http import HttpResponse

            if template_name == "exporter.html" and context and context.get("exported_data"):
                exported_data_str = context["exported_data"]
                # Create a simplified version of the exporter template
                html_content = f"""<!doctype html>
<html>
    <head>
        <script id="posthog-exported-data" type="application/json">{exported_data_str}</script>
        <script>
            try {{
                window.POSTHOG_EXPORTED_DATA = JSON.parse(
                    JSON.parse(document.getElementById('posthog-exported-data').textContent)
                );
            }} catch (e) {{
                console.error('Failed to parse exported data:', e);
                window.POSTHOG_EXPORTED_DATA = {{}};
            }}
        </script>
    </head>
    <body>
        <div>{exported_data_str}</div>
        <div id="root"></div>
    </body>
</html>"""
                return HttpResponse(html_content)
            else:
                # For non-exporter templates, return a simple response
                return HttpResponse('<html><body>{"dashboard": "content"}</body></html>')

        mock_render_template.side_effect = mock_render_side_effect
        return test_func(self, *args, **kwargs)

    return wrapper


@parameterized.expand(
    [
        ["http://localhost:8000/something", "http://localhost:8000/something.png"],
        [
            "http://localhost:8000/something?query=string",
            "http://localhost:8000/something.png?query=string",
        ],
        [
            "http://localhost:8000/something?query=string&another=one",
            "http://localhost:8000/something.png?query=string&another=one",
        ],
        [
            "http://localhost:8000/something?query=string&another=one#withhash",
            "http://localhost:8000/something.png?query=string&another=one#withhash",
        ],
        [
            "http://localhost:8000/something#withhash",
            "http://localhost:8000/something.png#withhash",
        ],
    ]
)
def test_shared_image_alternative(url: str, expected_url: str) -> None:
    assert shared_url_as_png(url) == expected_url


class TestSharing(APIBaseTest):
    dashboard: Dashboard = None  # type: ignore
    insight: Insight = None  # type: ignore

    insight_filter_dict = {
        "events": [{"id": "$pageview"}],
        "properties": [{"key": "$browser", "value": "Mac OS X"}],
    }

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.dashboard = Dashboard.objects.create(team=cls.team, name="example dashboard", created_by=cls.user)
        cls.insight = Insight.objects.create(
            filters=Filter(data=cls.insight_filter_dict).to_dict(),
            team=cls.team,
            created_by=cls.user,
        )

    @freeze_time("2022-01-01")
    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_gets_sharing_config(self, patched_exporter_task: Mock):
        assert SharingConfiguration.objects.count() == 0

        # First get the initial config (not saved yet)
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing")
        assert SharingConfiguration.objects.count() == 0
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data == {
            "access_token": data["access_token"],
            "created_at": None,
            "enabled": False,
            "password_required": False,
            "settings": None,
            "share_passwords": [],
        }

    @freeze_time("2022-01-01")
    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_does_not_change_token_when_toggling_enabled_state(self, patched_exporter_task: Mock):
        assert SharingConfiguration.objects.count() == 0
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True},
        )
        initial_data = response.json()
        assert SharingConfiguration.objects.count() == 1
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing")
        assert response.json() == {
            "access_token": initial_data["access_token"],
            "created_at": "2022-01-01T00:00:00Z",
            "enabled": True,
            "password_required": False,
            "settings": None,
            "share_passwords": [],
        }

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": False},
        )
        assert response.json() == {
            "access_token": initial_data["access_token"],
            "created_at": "2022-01-01T00:00:00Z",
            "enabled": False,
            "password_required": False,
            "settings": None,
            "share_passwords": [],
        }

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_can_edit_enabled_state(self, patched_exporter_task: Mock):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True},
        )
        data = response.json()
        assert response.status_code == status.HTTP_200_OK
        assert data["enabled"]

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}")

        assert response.json()["is_shared"]
        assert ActivityLog.objects.filter(scope="SharingConfiguration").count() == 0

        self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": False},
        )

        dashboard_sharing_logs = ActivityLog.objects.filter(
            scope="Dashboard", activity__in=["sharing enabled", "sharing disabled"]
        ).order_by("created_at")
        assert [(x.activity, x.user_id) for x in dashboard_sharing_logs] == [
            ("sharing enabled", self.user.id),
            ("sharing disabled", self.user.id),
        ]

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_can_edit_enabled_state_for_insight(self, patched_exporter_task: Mock):
        assert ActivityLog.objects.filter(scope="SharingConfiguration").count() == 0

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{self.insight.id}/sharing",
            {"enabled": True},
        )
        data = response.json()
        assert response.status_code == status.HTTP_200_OK
        assert data["enabled"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{self.insight.id}/sharing",
            {"enabled": False},
        )
        data = response.json()
        assert response.status_code == status.HTTP_200_OK
        assert data["enabled"] is False

        insight_logs = ActivityLog.objects.filter(scope="Insight").order_by("created_at")
        assert [x.activity for x in list(insight_logs)] == [
            "sharing enabled",
            "exported for opengraph image",
            "sharing disabled",
        ]

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_exports_image_when_sharing(self, patched_exporter_task: Mock):
        assert ExportedAsset.objects.count() == 0

        self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True},
        )

        assert ExportedAsset.objects.count() == 1
        asset = ExportedAsset.objects.first()
        assert asset is not None
        assert asset.export_format == "image/png"

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_should_adopt_legacy_share_token_on_read_without_enabling(self, patched_exporter_task: Mock):
        dashboard = Dashboard.objects.create(team=self.team, name="example dashboard", created_by=self.user)
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing")
        initial_token = response.json()["access_token"]
        assert initial_token
        assert not response.json()["enabled"]

        dashboard.share_token = "my_test_token"
        dashboard.is_shared = True
        dashboard.save()

        # A read adopts the legacy token onto the config, but must not turn sharing on: a stale
        # legacy is_shared=True can never make a private dashboard public without an explicit PATCH.
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing")
        data = response.json()
        assert data["access_token"] == "my_test_token"
        assert not data["enabled"]

        dashboard.share_token = None
        dashboard.is_shared = False
        dashboard.save()

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing")
        data = response.json()
        assert data["access_token"] == "my_test_token"
        assert not data["enabled"]

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_read_does_not_enable_sharing_from_stale_legacy_is_shared(self, _patched_exporter_task: Mock):
        # An active (disabled) config exists with one token while the dashboard still carries a stale
        # legacy share_token + is_shared=True pointing at a different token. Reading the sharing config
        # must never persist enabled=True: a plain GET can't make a private dashboard publicly reachable.
        dashboard = Dashboard.objects.create(team=self.team, name="critical dashboard", created_by=self.user)
        active_config = SharingConfiguration.objects.create(
            team=self.team,
            dashboard=dashboard,
            enabled=False,
            access_token="active_token",
        )
        dashboard.share_token = "stale_legacy_token"
        dashboard.is_shared = True
        dashboard.save(update_fields=["share_token", "is_shared"])

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing")

        assert response.status_code == status.HTTP_200_OK
        assert not response.json()["enabled"]
        active_config.refresh_from_db()
        assert active_config.enabled is False
        # No active config for this dashboard may end up enabled off the back of a read.
        assert not SharingConfiguration.objects.filter(
            dashboard=dashboard, expires_at__isnull=True, enabled=True
        ).exists()

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_should_not_be_affected_by_collaboration_rules(self, _patched_exporter_task: Mock):
        other_user = User.objects.create_and_join(self.organization, "a@x.com", None)
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="example dashboard",
            created_by=other_user,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing",
            {"enabled": True},
        )

        assert response.status_code == 200

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_should_not_get_deleted_item(self, _patched_exporter_task: Mock):
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="example dashboard",
            created_by=self.user,
            share_token="my_test_token",
            is_shared=True,
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing",
            {"enabled": True},
        )
        response = self.client.get(f"/shared_dashboard/my_test_token")
        assert response.status_code == 200
        response = self.client.patch(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}", {"deleted": True})
        assert response.status_code == 200
        response = self.client.get(f"/shared_dashboard/my_test_token")
        assert response.status_code == 404

    @parameterized.expand(
        [
            "/exporter/something.png?token=my_test_token",
            "/shared_dashboard/something.png?token=my_test_token",
        ]
    )
    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    @patch("products.exports.backend.models.exported_asset.object_storage.get_presigned_url")
    @patch("posthog.api.sharing.asset_for_token")
    def test_can_get_shared_dashboard_asset_with_no_content_but_content_location(
        self,
        url: str,
        patched_asset_for_token,
        patched_get_presigned_url,
        _patched_exporter_task: Mock,
    ) -> None:
        asset = ExportedAsset.objects.create(
            team_id=self.team.id,
            export_format=ExportedAsset.ExportFormat.PNG,
            content=None,
            content_location="some object url",
        )
        patched_asset_for_token.return_value = (asset, None)

        patched_get_presigned_url.return_value = "https://s3.example.com/presigned-url"

        response = self.client.get(url)

        assert response.status_code == 302
        assert response["Location"] == "https://s3.example.com/presigned-url"
        patched_get_presigned_url.assert_called_once_with(
            "some object url",
            content_type="image/png",
            content_disposition=None,
        )

    @parameterized.expand(["insights", "dashboards"])
    @patch("products.exports.backend.models.exported_asset.object_storage.get_presigned_url")
    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_shared_thing_can_generate_open_graph_image(
        self, type: str, patched_exporter_task: Mock, patched_get_presigned_url: Mock
    ) -> None:
        patched_get_presigned_url.return_value = "https://s3.example.com/presigned-url"

        target = self.insight if type == "insights" else self.dashboard

        self._setup_patched_exporter(patched_exporter_task)

        assert ExportedAsset.objects.count() == 0

        share_response = self.client.patch(
            f"/api/projects/{self.team.id}/{type}/{target.pk}/sharing",
            {"enabled": True},
        )
        access_token = share_response.json()["access_token"]

        item_opengraph_image = self.client.get("/shared/" + access_token + ".png")

        assert ExportedAsset.objects.count() == 1
        assert item_opengraph_image.status_code == 302
        assert item_opengraph_image["Location"] == "https://s3.example.com/presigned-url"

    @parameterized.expand(["insights", "dashboards"])
    @patch("products.exports.backend.models.exported_asset.object_storage.get_presigned_url")
    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_shared_thing_can_reuse_existing_generated_open_graph_image(
        self, type: str, patched_exporter_task: Mock, patched_get_presigned_url: Mock
    ) -> None:
        patched_get_presigned_url.return_value = "https://s3.example.com/presigned-url"

        self._setup_patched_exporter(patched_exporter_task)

        target = self.insight if type == "insights" else self.dashboard

        share_response = self.client.patch(
            f"/api/projects/{self.team.id}/{type}/{target.pk}/sharing",
            {"enabled": True},
        )
        access_token = share_response.json()["access_token"]

        # generation was called when sharing was enabled
        patched_exporter_task.reset_mock()

        item_opengraph_image = self.client.get("/shared/" + access_token + ".png")

        # and not again on loading the image
        patched_exporter_task.assert_not_called()

        assert ExportedAsset.objects.count() == 1
        assert item_opengraph_image.status_code == 302
        assert item_opengraph_image["Location"] == "https://s3.example.com/presigned-url"

    def _setup_patched_exporter(self, patched_exporter_task):
        def add_content_location_on_task_run(*args, **kwargs):
            asset = ExportedAsset.objects.get(team_id=self.team.id)
            asset.content_location = "some object url"
            asset.save()

            return MagicMock()

        patched_exporter_task.side_effect = add_content_location_on_task_run

    @parameterized.expand(["insights", "dashboards"])
    @patch("products.exports.backend.models.exported_asset.object_storage.get_presigned_url")
    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_shared_insight_can_regenerate_stale_existing_generated_open_graph_image(
        self, type: str, patched_exporter_task: Mock, patched_get_presigned_url: Mock
    ) -> None:
        patched_get_presigned_url.return_value = "https://s3.example.com/presigned-url"
        self._setup_patched_exporter(patched_exporter_task)

        target = self.insight if type == "insights" else self.dashboard

        # Create an asset that's past its expiry (PNG assets expire after 180 days)
        time_in_the_past = now() - timedelta(days=181)
        with freeze_time(time_in_the_past):
            share_response = self.client.patch(
                f"/api/projects/{self.team.id}/{type}/{target.pk}/sharing",
                {"enabled": True},
            )
            # enabling creates an asset with expires_after set to 180 days from creation
            assert ExportedAsset.objects_including_ttl_deleted.count() == 1
            original_asset = ExportedAsset.objects_including_ttl_deleted.first()

        access_token = share_response.json()["access_token"]

        # Asset is now expired and filtered out by the default manager
        assert ExportedAsset.objects.count() == 0

        item_opengraph_image = self.client.get("/shared/" + access_token + ".png")
        assert item_opengraph_image.status_code == 302
        assert item_opengraph_image["Location"] == "https://s3.example.com/presigned-url"

        assert ExportedAsset.objects.count() == 1
        final_asset = ExportedAsset.objects.first()
        assert final_asset is not None
        assert original_asset is not None
        assert final_asset.id != original_asset.id

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_can_refresh_sharing_access_token_for_dashboard(self, patched_exporter_task: Mock):
        # Enable sharing
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True},
        )
        initial_data = response.json()
        initial_token = initial_data["access_token"]
        assert initial_token

        # Refresh the token
        response = self.client.post(f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing/refresh/")
        assert response.status_code == status.HTTP_200_OK
        refreshed_data = response.json()

        # Token should be different
        assert refreshed_data["access_token"] != initial_token
        assert refreshed_data["enabled"] is True

        # Verify the token persists
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing")
        assert response.json()["access_token"] == refreshed_data["access_token"]

        # Verify activity log was created
        activity_logs = ActivityLog.objects.filter(scope="Dashboard", activity="access token refreshed")
        assert activity_logs.count() == 1
        first = activity_logs.first()
        assert first is not None
        assert first.item_id == str(self.dashboard.id)

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_can_refresh_sharing_access_token_for_insight(self, patched_exporter_task: Mock):
        # First enable sharing
        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{self.insight.id}/sharing",
            {"enabled": True},
        )
        initial_data = response.json()
        initial_token = initial_data["access_token"]
        assert initial_token

        # Refresh the token
        response = self.client.post(f"/api/projects/{self.team.id}/insights/{self.insight.id}/sharing/refresh/")
        assert response.status_code == status.HTTP_200_OK
        refreshed_data = response.json()

        # Token should be different
        assert refreshed_data["access_token"] != initial_token
        assert refreshed_data["enabled"] is True

        # Verify activity log was created
        activity_logs = ActivityLog.objects.filter(activity="access token refreshed")
        assert activity_logs.count() == 1
        first = activity_logs.first()
        assert first is not None
        assert first.item_id == str(self.insight.id)

    @freeze_time("2025-01-01 00:00:00")
    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_refresh_token_grace_period(self, patched_exporter_task: Mock):
        # Enable sharing
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True},
        )
        initial_token = response.json()["access_token"]

        # Refresh the token
        response = self.client.post(f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing/refresh/")
        assert response.status_code == status.HTTP_200_OK
        new_token = response.json()["access_token"]
        assert new_token != initial_token

        # Old token should still work immediately after refresh
        response = self.client.get(f"/shared/{initial_token}")
        assert response.status_code == 200

        # New token should also work
        response = self.client.get(f"/shared/{new_token}")
        assert response.status_code == 200

        # Within grace period (4 minutes later), old token should still work
        # Note: Grace period is 5 minutes (SHARING_TOKEN_GRACE_PERIOD_SECONDS)
        with freeze_time("2025-01-01 00:04:00"):
            response = self.client.get(f"/shared/{initial_token}")
            assert response.status_code == 200

        # After grace period (6 minutes later), old token should not work
        with freeze_time("2025-01-01 00:06:00"):
            response = self.client.get(f"/shared/{initial_token}")
            assert response.status_code == 404

        # New token should still work after grace period
        with freeze_time("2025-01-01 00:06:00"):
            response = self.client.get(f"/shared/{new_token}")
            assert response.status_code == 200

    def test_token_uniqueness_constraints(self):
        """Test that token uniqueness is enforced at the database level"""
        from posthog.models.sharing_configuration import SharingConfiguration

        # Create first sharing configuration with a specific token
        config1 = SharingConfiguration.objects.create(
            team=self.team,
            dashboard=self.dashboard,
            enabled=True,
        )
        # Token should be auto-generated
        assert config1.access_token is not None
        original_token = config1.access_token

        # Try to manually set another config with the same token - should fail due to DB constraint
        config2 = SharingConfiguration(
            team=self.team,
            insight=self.insight,
            enabled=True,
            access_token=original_token,  # Duplicate token
        )

        # This should raise IntegrityError due to unique constraint
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            config2.save()

    def test_token_rotation_creates_new_config(self):
        """Test that token rotation creates a new configuration and expires the old one"""
        from posthog.models.sharing_configuration import SharingConfiguration

        # Enable sharing
        self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True},
        )
        original_config = SharingConfiguration.objects.get(dashboard=self.dashboard, expires_at__isnull=True)

        # Refresh the token
        response = self.client.post(f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing/refresh/")
        assert response.status_code == status.HTTP_200_OK
        new_token = response.json()["access_token"]

        # Should have created a new config
        new_config = SharingConfiguration.objects.get(dashboard=self.dashboard, expires_at__isnull=True)
        assert new_config.access_token == new_token
        assert new_config.pk != original_config.pk

        # Old config should be expired
        original_config.refresh_from_db()
        assert original_config.expires_at is not None
        assert original_config.expires_at > timezone.now()  # Should be in the future

    @parameterized.expand(
        [
            # action, expected active configs after the call: reads leave duplicates alone,
            # authorized writes (patch/refresh) collapse them to one.
            ("get", 2),
            ("patch", 1),
            ("refresh", 1),
        ]
    )
    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_sharing_endpoints_succeed_with_duplicate_active_configs(
        self, action: str, expected_active_configs: int, _patched_exporter_task: Mock
    ) -> None:
        share_settings = {"whitelabel": True, "hideExtraDetails": True}
        dashboard = Dashboard.objects.create(team=self.team, name="duplicate sharing dashboard", created_by=self.user)
        for token in ("duplicate_token_one", "duplicate_token_two"):
            SharingConfiguration.objects.create(
                team=self.team,
                dashboard=dashboard,
                enabled=True,
                access_token=token,
                settings=share_settings,
            )

        base_url = f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing"
        if action == "get":
            response = self.client.get(base_url)
        elif action == "patch":
            response = self.client.patch(base_url, {"enabled": True})
        else:
            response = self.client.post(f"{base_url}/refresh/")

        assert response.status_code == status.HTTP_200_OK
        assert (
            SharingConfiguration.objects.filter(dashboard=dashboard, expires_at__isnull=True).count()
            == expected_active_configs
        )
        body = response.json()
        assert body["enabled"] is True
        assert body["settings"] == share_settings

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_legacy_dashboard_share_token_does_not_500_when_token_already_used(
        self, _patched_exporter_task: Mock
    ) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="legacy token dashboard", created_by=self.user)
        SharingConfiguration.objects.create(
            team=self.team,
            dashboard=dashboard,
            enabled=True,
            access_token="active_token",
        )
        expired_config = SharingConfiguration.objects.create(
            team=self.team,
            dashboard=dashboard,
            enabled=True,
            access_token="legacy_token",
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        dashboard.share_token = expired_config.access_token
        dashboard.is_shared = True
        dashboard.save(update_fields=["share_token", "is_shared"])

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing")

        assert response.status_code == status.HTTP_200_OK
        dashboard.refresh_from_db()
        assert dashboard.share_token == "active_token"
        assert dashboard.is_shared is True
        assert response.json()["access_token"] == "active_token"

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_sharing_configuration_settings_field_defaults(self, patched_exporter_task: Mock):
        """Test that settings field defaults to empty dict"""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "settings" in data
        assert data["settings"] is None

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_can_update_settings_field(self, patched_exporter_task: Mock):
        """Test that settings field can be updated"""
        # First enable sharing
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True},
        )
        assert response.status_code == status.HTTP_200_OK

        # Update settings
        settings_data = {"whitelabel": True, "customSetting": "value"}
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"settings": settings_data},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["settings"] == {
            "whitelabel": True,
        }

        # Verify settings persists
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing")
        assert response.json()["settings"] == {
            "whitelabel": True,
        }

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_settings_preserved_on_token_rotation(self, patched_exporter_task: Mock):
        """Test that settings are preserved when rotating access tokens"""
        # Enable sharing with comprehensive settings
        settings_data = {
            "whitelabel": True,
            "noHeader": True,
            "showInspector": False,
            "legend": True,
            "detailed": False,
        }
        settings_data_with_custom_option = {
            **settings_data,
            "customOption": "test2",
        }
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True, "settings": settings_data_with_custom_option},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["settings"] == settings_data

        # Refresh the token
        response = self.client.post(f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing/refresh/")
        assert response.status_code == status.HTTP_200_OK

        # Settings should be preserved
        assert response.json()["settings"] == settings_data

    # @freeze_time("2023-12-15")  # Before ship date

    # def test_all_query_params_work_for_old_configs(self, patched_exporter_task: Mock):
    #     """Test that all query params work for configurations created before ship date"""
    #     # Ensure organization has white labelling feature
    #     self.organization.available_product_features = [
    #         {"key": AvailableFeature.WHITE_LABELLING, "name": "white_labelling"},
    #     ]
    #     self.organization.save()

    #     self.client.force_login(self.user)

    #     response = self.client.patch(
    #         f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
    #         {"enabled": True},
    #     )
    #     access_token = response.json()["access_token"]

    #     # Test all options via query params work for old config
    #     response = self.client.get(
    #         f"/shared/{access_token}?whitelabel=true&noHeader=true&legend=true&detailed=true&showInspector=true"
    #     )
    #     assert response.status_code == 200
    #     content = response.content.decode()
    #     assert '\\"whitelabel\\": true' in content
    #     assert '\\"noHeader\\": true' in content
    #     assert '\\"legend\\": true' in content
    #     assert '\\"detailed\\": true' in content
    #     assert '\\"showInspector\\": true' in content

    # @freeze_time("2025-10-15")  # After ship date

    # def test_all_query_params_ignored_for_new_configs(self, patched_exporter_task: Mock):
    #     """Test that all query params are ignored for configurations created after ship date"""
    #     # Ensure organization has white labelling feature
    #     self.organization.available_product_features = [
    #         {"key": AvailableFeature.WHITE_LABELLING, "name": "white_labelling"},
    #     ]
    #     self.organization.save()

    #     self.client.force_login(self.user)

    #     response = self.client.patch(
    #         f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
    #         {"enabled": True},
    #     )

    #     assert response.status_code == 200
    #     access_token = response.json()["access_token"]

    #     # Test all options via query params are ignored for new config
    #     response = self.client.get(f"/shared/{access_token}?whitelabel=true&noHeader=true&legend=true&detailed=true")
    #     assert response.status_code == 200
    #     content = response.content.decode()
    #     # None of the options should be active since they're not in settings
    #     assert '\\"whitelabel\\": true' not in content
    #     assert '\\"noHeader\\": true' not in content
    #     assert '\\"legend\\": true' not in content
    #     assert '\\"detailed\\": true' not in content

    # @freeze_time("2025-10-15")  # After ship date

    # def test_all_options_from_settings_work_for_new_configs(self, patched_exporter_task: Mock):
    #     """Test that all options from settings work for new configurations"""
    #     # Create sharing configuration with all options in settings
    #     self.organization.available_product_features = [
    #         {"key": AvailableFeature.WHITE_LABELLING, "name": "white_labelling"},
    #     ]
    #     self.organization.save()

    #     self.client.force_login(self.user)

    #     settings_data = {"whitelabel": True, "noHeader": True, "legend": True, "detailed": True, "showInspector": True}
    #     response = self.client.patch(
    #         f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
    #         {"enabled": True, "settings": settings_data},
    #     )
    #     access_token = response.json()["access_token"]

    #     # Test all options from settings work
    #     response = self.client.get(f"/shared/{access_token}")
    #     assert response.status_code == 200
    #     content = response.content.decode()
    #     assert '\\"whitelabel\\": true' in content
    #     assert '\\"noHeader\\": true' in content
    #     assert '\\"legend\\": true' in content
    #     assert '\\"detailed\\": true' in content
    #     assert '\\"showInspector\\": true' in content

    # @freeze_time("2025-10-15")  # After ship date

    # def test_settings_override_query_params_for_new_configs(self, patched_exporter_task: Mock):
    #     """Test that settings take precedence over query params for configurations created after ship date"""
    #     # Ensure organization has white labelling feature
    #     self.organization.available_product_features = [
    #         {"key": AvailableFeature.WHITE_LABELLING, "name": "white_labelling"},
    #     ]
    #     self.organization.save()

    #     # Force login to ensure authentication state is correct
    #     self.client.force_login(self.user)

    #     # Create sharing configuration with specific settings (whitelabel=True, noHeader=False)
    #     settings_data = {"whitelabel": True, "noHeader": False, "legend": True}
    #     response = self.client.patch(
    #         f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
    #         {"enabled": True, "settings": settings_data},
    #     )
    #     access_token = response.json()["access_token"]

    #     # Test with conflicting query params - should use settings, not query params
    #     response = self.client.get(f"/shared/{access_token}?whitelabel=false&noHeader=true&legend=false&detailed=true")
    #     assert response.status_code == 200
    #     content = response.content.decode()

    #     # Should use settings values, not query param values
    #     assert '\\"whitelabel\\": true' in content  # settings: true, query: false -> should be true
    #     assert '\\"legend\\": true' in content  # settings: true, query: false -> should be true

    #     # Should NOT have noHeader (settings: false, query: true -> should be false/not present)
    #     assert '\\"noHeader\\": true' not in content

    #     # Should NOT have detailed (not in settings, query: true -> should not be present)
    #     assert '\\"detailed\\": true' not in content

    @parameterized.expand(["insights", "dashboards"])
    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_settings_field_works_for_both_insights_and_dashboards(self, type: str, patched_exporter_task: Mock):
        """Test that settings field works for both insights and dashboards"""
        target = self.insight if type == "insights" else self.dashboard
        settings_data = {
            "whitelabel": True,
            "noHeader": False,
            "showInspector": True,
            "legend": False,
            "detailed": True,
        }
        settings_data_with_custom_option = {
            **settings_data,
            "customOption": "test",
        }

        response = self.client.patch(
            f"/api/projects/{self.team.id}/{type}/{target.pk}/sharing",
            {"enabled": True, "settings": settings_data_with_custom_option},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["settings"] == settings_data

        # Verify settings persists
        response = self.client.get(f"/api/projects/{self.team.id}/{type}/{target.pk}/sharing")
        assert response.json()["settings"] == settings_data

    def test_sharing_configuration_model_settings_default(self):
        """Test that the model's settings field defaults to empty dict"""
        from posthog.models.sharing_configuration import SharingConfiguration

        config = SharingConfiguration.objects.create(
            team=self.team,
            dashboard=self.dashboard,
            enabled=True,
        )
        assert config.settings is None

        # Test with explicit settings
        config_with_settings = SharingConfiguration.objects.create(
            team=self.team, insight=self.insight, enabled=True, settings={"whitelabel": True, "custom": "value"}
        )
        assert config_with_settings.settings == {"whitelabel": True, "custom": "value"}

    def test_rotate_access_token_preserves_settings(self):
        """Test that rotating access token preserves the settings"""
        from posthog.models.sharing_configuration import SharingConfiguration

        # Create config with comprehensive settings
        settings_data = {
            "whitelabel": True,
            "noHeader": False,
            "showInspector": True,
            "legend": False,
            "detailed": True,
            "customSetting": "preserved",
        }
        original_config = SharingConfiguration.objects.create(
            team=self.team, dashboard=self.dashboard, enabled=True, settings=settings_data
        )

        # Rotate token
        new_config = original_config.rotate_access_token()

        # Settings should be preserved
        assert new_config.settings == settings_data
        assert new_config.access_token != original_config.access_token
        assert new_config.enabled == original_config.enabled


class TestSharingConfigurationSerializerValidation(APIBaseTest):
    """Test the serializer validation for settings field"""

    dashboard: Dashboard = None  # type: ignore

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.dashboard = Dashboard.objects.create(team=cls.team, name="test dashboard", created_by=cls.user)

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_valid_settings_are_accepted(self, patched_exporter_task: Mock):
        """Test that valid settings are accepted and validated"""
        valid_settings = {
            "whitelabel": True,
            "noHeader": False,
            "showInspector": True,
            "legend": False,
            "detailed": True,
            "theme": "dark",
        }

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True, "settings": valid_settings},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["settings"] == valid_settings

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_partial_settings_are_filled_with_defaults(self, patched_exporter_task: Mock):
        """Test that partial settings are filled with defaults during validation"""
        partial_settings = {"whitelabel": True, "legend": True, "theme": "light"}

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True, "settings": partial_settings},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Should have defaults filled in
        expected_settings = {
            "whitelabel": True,
            "legend": True,
            "theme": "light",
        }
        assert data["settings"] == expected_settings

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_unknown_settings_are_filtered_out(self, patched_exporter_task: Mock):
        """Test that unknown settings fields are filtered out during validation"""
        settings_with_unknown = {
            "whitelabel": True,
            "unknownField": "should be removed",
            "anotherBadField": 123,
            "legend": False,
        }

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True, "settings": settings_with_unknown},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Unknown fields should be filtered out, defaults filled in
        expected_settings = {
            "whitelabel": True,
            "legend": False,
        }
        assert data["settings"] == expected_settings

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_null_settings_are_accepted(self, patched_exporter_task: Mock):
        """Test that null settings are accepted"""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True, "settings": None},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["settings"] is None

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_empty_settings_get_defaults(self, patched_exporter_task: Mock):
        """Test that empty settings dictionary gets filled with defaults"""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True, "settings": {}},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Empty dict should be filled with defaults
        assert data["settings"] == {}

    def test_invalid_settings_type_rejected(self):
        """Test that invalid settings type is rejected"""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True, "settings": "invalid string"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        errors = response.json()
        assert "settings" in errors["detail"]
        assert "Invalid settings format" in str(errors["detail"])

    def test_settings_validation_works_for_insights_too(self):
        """Test that settings validation works for insights as well as dashboards"""
        insight = Insight.objects.create(
            filters={"events": [{"id": "$pageview"}]},
            team=self.team,
            created_by=self.user,
        )

        valid_settings = {"whitelabel": True, "detailed": True}

        with patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow"):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{insight.id}/sharing",
                {"enabled": True, "settings": valid_settings},
            )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        expected_settings = {
            "whitelabel": True,
            "detailed": True,
        }
        assert data["settings"] == expected_settings

    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    @mock_exporter_template
    def test_shared_resource_blocked_when_organization_disallows_public_sharing(self, _patched_exporter_task: Mock):
        """Test that shared resources return 404 when organization.allow_publicly_shared_resources is False and feature is enabled"""
        self.organization.available_product_features = [
            {"key": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS, "name": "organization_security_settings"},
        ]
        self.organization.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True},
        )
        assert response.status_code == status.HTTP_200_OK
        access_token = response.json()["access_token"]

        response = self.client.get(f"/shared/{access_token}")
        assert response.status_code == 200

        self.organization.allow_publicly_shared_resources = False
        self.organization.save()

        response = self.client.get(f"/shared/{access_token}")
        assert response.status_code == 404

    @parameterized.expand(
        [
            # Org has public sharing DISABLED: only purpose-scoped tokens get through, and only at the matching surface.
            ("sharing_off_public_on_page", False, "public", "page", 404),
            ("sharing_off_public_on_file", False, "public", "file", 404),
            ("sharing_off_render_on_page", False, "render", "page", 200),
            ("sharing_off_render_on_file", False, "render", "file", 404),
            ("sharing_off_subscription_on_page", False, "subscription", "page", 404),
            ("sharing_off_subscription_on_file", False, "subscription", "file", 200),
            # Org has public sharing ENABLED: public tokens work on both surfaces; purpose tokens still pinned to their surface.
            ("sharing_on_public_on_page", True, "public", "page", 200),
            ("sharing_on_public_on_file", True, "public", "file", 200),
            ("sharing_on_render_on_page", True, "render", "page", 200),
            ("sharing_on_render_on_file", True, "render", "file", 404),
            ("sharing_on_subscription_on_page", True, "subscription", "page", 404),
            ("sharing_on_subscription_on_file", True, "subscription", "file", 200),
        ]
    )
    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    @patch("posthog.api.sharing.render_template")
    def test_exported_asset_token_access_matrix(
        self,
        _name: str,
        sharing_enabled: bool,
        token_kind: str,
        url_kind: str,
        expected_status: int,
        mock_render_template: Mock,
        _patched_exporter_task: Mock,
    ) -> None:
        """
        Truth table for ExportedAsset token access. Two axes interact:
          - organization.allow_publicly_shared_resources (on/off)
          - JWT purpose claim (public / render / subscription_delivery) vs URL surface (page / file).

        Render and subscription_delivery tokens are internal-purpose and bypass the org-level public-sharing
        block, but each is pinned to a single URL surface so an intercepted token can't be repurposed.
        """
        mock_render_template.return_value = HttpResponse("<html><body>POSTHOG_EXPORTED_DATA</body></html>")

        self.organization.available_product_features = [
            {"key": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS, "name": "organization_security_settings"},
        ]
        self.organization.allow_publicly_shared_resources = sharing_enabled
        self.organization.save()

        asset = ExportedAsset.objects.create(
            team=self.team,
            dashboard=self.dashboard,
            export_format=ExportedAsset.ExportFormat.PNG,
            content=b"image",
        )

        token = {
            "public": lambda: asset.get_public_content_url().split("token=")[1],
            "render": lambda: get_render_access_token(asset),
            "subscription": lambda: asset.get_subscription_delivery_content_url().split("token=")[1],
        }[token_kind]()

        path = {
            "page": "/exporter",
            "file": f"/exporter/{asset.filename}",
        }[url_kind]

        response = self.client.get(f"{path}?token={token}")
        assert response.status_code == expected_status

    @patch("products.exports.backend.models.exported_asset.object_storage.get_presigned_url")
    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_exported_asset_public_url_blocked_when_organization_disallows_public_sharing(
        self, _patched_exporter_task: Mock, patched_get_presigned_url: Mock
    ):
        """
        Regression test: previously, disabling org-level public sharing only blocked
        `/shared/<token>` (SharingConfiguration path) but left `/exporter/...?token=<jwt>`
        (ExportedAsset public token path) returning content. Both surfaces must respect
        the kill switch.
        """
        patched_get_presigned_url.return_value = "https://s3.example.com/presigned-url"
        self.organization.available_product_features = [
            {"key": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS, "name": "organization_security_settings"},
        ]
        self.organization.save()

        # Enable sharing and create a publicly-accessible ExportedAsset for the dashboard.
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True},
        )
        assert response.status_code == status.HTTP_200_OK

        asset = ExportedAsset.objects.create(
            team=self.team,
            dashboard=self.dashboard,
            export_format=ExportedAsset.ExportFormat.PNG,
            content_location="some object url",
        )
        exporter_url = asset.get_public_content_url()

        # Sanity check: public token URL works while public sharing is allowed.
        response = self.client.get(exporter_url)
        assert response.status_code == 302

        # Disable public sharing at the org level.
        self.organization.allow_publicly_shared_resources = False
        self.organization.save()

        # ExportedAsset public token URL must now be blocked, same as /shared/...
        response = self.client.get(exporter_url)
        assert response.status_code == 404

    @patch("products.exports.backend.models.exported_asset.object_storage.get_presigned_url")
    @patch("products.exports.backend.api.exports.ExportedAssetSerializer._start_export_workflow")
    def test_exported_asset_public_url_blocked_for_password_protected_share_when_disallowed(
        self, _patched_exporter_task: Mock, patched_get_presigned_url: Mock
    ):
        """
        A known ExportedAsset public token URL must not bypass the org-level kill switch even
        when the underlying SharingConfiguration is password-protected.
        """
        patched_get_presigned_url.return_value = "https://s3.example.com/presigned-url"
        self.organization.available_product_features = [
            {"key": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS, "name": "organization_security_settings"},
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "access_control"},
        ]
        self.organization.save()

        SharingConfiguration.objects.create(
            team=self.team,
            dashboard=self.dashboard,
            enabled=True,
            password_required=True,
        )
        asset = ExportedAsset.objects.create(
            team=self.team,
            dashboard=self.dashboard,
            export_format=ExportedAsset.ExportFormat.PNG,
            content_location="some object url",
        )
        exporter_url = asset.get_public_content_url()

        self.organization.allow_publicly_shared_resources = False
        self.organization.save()

        response = self.client.get(exporter_url)
        assert response.status_code == 404


class TestSharePasswordLogging(APIBaseTest):
    """Test the _log_share_password_attempt function for activity logging"""

    dashboard: Dashboard = None  # type: ignore
    sharing_config: SharingConfiguration = None  # type: ignore

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.dashboard = Dashboard.objects.create(team=cls.team, name="test dashboard", created_by=cls.user)
        cls.sharing_config = SharingConfiguration.objects.create(
            team=cls.team,
            dashboard=cls.dashboard,
            access_token="test_access_token_123456",
            enabled=True,
            password_required=True,
        )

    def test_log_share_password_attempt_success(self):
        """Test successful password validation logging"""
        # Create a SharePassword
        share_password = SharePassword.objects.create(
            sharing_configuration=self.sharing_config,
            password_hash="test_hash",
            note="Test password for dashboard access",
            created_by=self.user,
        )

        # Mock request with IP
        mock_request = Mock()
        mock_request.META = {"REMOTE_ADDR": "192.168.1.100"}
        mock_request.headers = {}

        # Clear any existing activity logs
        ActivityLog.objects.filter(scope="Dashboard").delete()

        # Call the function
        _log_share_password_attempt(
            resource=self.sharing_config, request=mock_request, success=True, validated_password=share_password
        )

        # Check activity log was created
        activity_logs = ActivityLog.objects.filter(scope="Dashboard")
        assert activity_logs.count() == 1

        log = activity_logs.first()
        assert log is not None
        assert log.activity == "share_login_success"
        assert log.team_id == self.team.id
        assert log.organization_id == self.team.organization.id
        assert log.user is None  # Anonymous user
        assert log.was_impersonated is False
        assert log.item_id == str(self.dashboard.id)  # Uses dashboard ID as item_id

        # Check detail contains expected data
        assert log.detail is not None
        assert log.detail["name"] == "test dashboard"  # Should now contain the actual dashboard name
        assert len(log.detail["changes"]) == 1

        change = log.detail["changes"][0]
        assert change["type"] == "Dashboard"
        assert change["action"] == "changed"
        assert change["field"] == "authentication_attempt"

        change_data = change["after"]
        assert change_data["access_token_suffix"] == "123456"  # Last 6 chars
        assert change_data["client_ip"] == "192.168.1.100"
        assert change_data["success"] is True
        assert change_data["resource_type"] == "dashboard"
        assert change_data["password_id"] == str(share_password.id)
        assert change_data["password_note"] == "Test password for dashboard access"

    def test_log_share_password_attempt_failure(self):
        """Test failed password validation logging"""
        # Mock request with different IP
        mock_request = Mock()
        mock_request.META = {"REMOTE_ADDR": "10.0.0.5"}
        mock_request.headers = {}

        # Clear any existing activity logs
        ActivityLog.objects.filter(scope="Dashboard").delete()

        # Call the function for failed attempt
        _log_share_password_attempt(resource=self.sharing_config, request=mock_request, success=False)

        # Check activity log was created
        activity_logs = ActivityLog.objects.filter(scope="Dashboard")
        assert activity_logs.count() == 1

        log = activity_logs.first()
        assert log is not None
        assert log.activity == "share_login_failed"
        assert log.team_id == self.team.id
        assert log.organization_id == self.team.organization.id
        assert log.user is None  # Anonymous user
        assert log.was_impersonated is False
        assert log.item_id == str(self.dashboard.id)  # Uses dashboard ID as item_id

        # Check detail contains expected data
        assert log.detail is not None
        assert log.detail["name"] == "test dashboard"  # Should now contain the actual dashboard name
        assert len(log.detail["changes"]) == 1

        change = log.detail["changes"][0]
        assert change["type"] == "Dashboard"
        assert change["action"] == "changed"
        assert change["field"] == "authentication_attempt"

        change_data = change["after"]
        assert change_data["access_token_suffix"] == "123456"  # Last 6 chars
        assert change_data["client_ip"] == "10.0.0.5"
        assert change_data["success"] is False
        assert change_data["resource_type"] == "dashboard"
        assert "password_id" not in change_data  # No password_id for failed attempts


class TestExportCacheKeyFlow(APIBaseTest):
    """Test that cache_keys parameter is correctly parsed and passed to InsightSerializer."""

    insight: Insight
    sharing_config: SharingConfiguration

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.insight = Insight.objects.create(
            team=cls.team,
            name="Test Insight",
            query={"kind": "TrendsQuery", "series": [{"event": "$pageview"}]},
        )
        cls.sharing_config = SharingConfiguration.objects.create(
            team=cls.team,
            insight=cls.insight,
            enabled=True,
        )

    @patch("posthog.caching.calculate_results.calculate_for_query_based_insight")
    @patch("products.product_analytics.backend.api.insight.fetch_cached_response_by_key")
    @mock_exporter_template
    def test_cache_keys_parameter_triggers_direct_cache_lookup(self, mock_fetch_cached, mock_calculate):
        """Test that cache_keys param causes InsightSerializer to use direct cache lookup and skip calculation."""
        cached_response = {
            "results": [{"count": 42}],
            "cache_key": "expected_cache_key_abc123",
            "last_refresh": "2024-01-01T00:00:00Z",
            "timezone": "UTC",
        }
        mock_fetch_cached.return_value = cached_response

        cache_keys = {str(self.insight.id): "expected_cache_key_abc123"}
        cache_keys_param = quote(json.dumps(cache_keys))

        response = self.client.get(f"/shared/{self.sharing_config.access_token}?cache_keys={cache_keys_param}")

        assert response.status_code == 200
        mock_fetch_cached.assert_called_once_with("expected_cache_key_abc123", team_id=self.insight.team_id)
        mock_calculate.assert_not_called()

    @patch("posthog.caching.calculate_results.calculate_for_query_based_insight")
    @patch("products.product_analytics.backend.api.insight.fetch_cached_response_by_key")
    @mock_exporter_template
    def test_cache_miss_falls_back_to_normal_calculation(self, mock_fetch_cached, mock_calculate):
        """Test that cache miss on expected key falls back to normal calculation."""
        from posthog.caching.fetch_from_cache import InsightResult

        mock_fetch_cached.return_value = None  # Cache miss
        mock_calculate.return_value = InsightResult(
            result=[{"count": 50}],
            cache_key="calculated_cache_key",
            is_cached=False,
            last_refresh=None,
            timezone="UTC",
        )

        cache_keys = {str(self.insight.id): "missing_cache_key"}
        cache_keys_param = quote(json.dumps(cache_keys))

        response = self.client.get(f"/shared/{self.sharing_config.access_token}?cache_keys={cache_keys_param}")

        assert response.status_code == 200
        mock_fetch_cached.assert_called_once_with("missing_cache_key", team_id=self.insight.team_id)
        mock_calculate.assert_called_once()

    @patch("posthog.caching.calculate_results.calculate_for_query_based_insight")
    @patch("products.product_analytics.backend.api.insight.fetch_cached_response_by_key")
    @mock_exporter_template
    def test_invalid_cache_keys_param_continues_without_it(self, mock_fetch_cached, mock_calculate):
        """Test that invalid cache_keys parameter is ignored and normal flow continues."""
        from posthog.caching.fetch_from_cache import InsightResult

        mock_calculate.return_value = InsightResult(
            result=[{"count": 25}],
            cache_key="normal_cache_key",
            is_cached=False,
            last_refresh=None,
            timezone="UTC",
        )

        # Pass invalid JSON as cache_keys
        response = self.client.get(f"/shared/{self.sharing_config.access_token}?cache_keys=not_valid_json")

        assert response.status_code == 200
        # fetch_cached_response_by_key should not be called since cache_keys parsing failed
        mock_fetch_cached.assert_not_called()
        mock_calculate.assert_called_once()


class TestSharedCohortInlining(APIBaseTest):
    @mock_exporter_template
    def test_shared_insight_inlines_referenced_cohort_names(self):
        from products.cohorts.backend.models.cohort import Cohort

        cohort = Cohort.objects.create(team=self.team, name="Power users")
        other_cohort = Cohort.objects.create(team=self.team, name="Churned users")  # not referenced

        insight = Insight.objects.create(
            team=self.team,
            name="Trend by cohort",
            query={
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    "breakdownFilter": {"breakdown_type": "cohort", "breakdown": [cohort.id]},
                },
            },
        )
        config = SharingConfiguration.objects.create(team=self.team, insight=insight, enabled=True)

        response = self.client.get(f"/shared/{config.access_token}")
        assert response.status_code == 200

        exported_cohorts = self._parse_exported_cohorts(response.content.decode())
        assert exported_cohorts == [{"id": cohort.id, "name": "Power users"}]
        assert other_cohort.id not in {c["id"] for c in exported_cohorts}

    @mock_exporter_template
    def test_shared_insight_without_cohort_references_returns_empty_list(self):
        insight = Insight.objects.create(
            team=self.team,
            name="No cohorts",
            query={
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                },
            },
        )
        config = SharingConfiguration.objects.create(team=self.team, insight=insight, enabled=True)

        response = self.client.get(f"/shared/{config.access_token}")
        assert response.status_code == 200
        assert self._parse_exported_cohorts(response.content.decode()) == []

    @mock_exporter_template
    def test_shared_dashboard_collects_cohorts_across_tiles(self):
        from products.cohorts.backend.models.cohort import Cohort
        from products.dashboards.backend.models.dashboard_tile import DashboardTile

        cohort_a = Cohort.objects.create(team=self.team, name="Cohort A")
        cohort_b = Cohort.objects.create(team=self.team, name="Cohort B")

        dashboard = Dashboard.objects.create(team=self.team, name="dash", created_by=self.user)
        insight_a = Insight.objects.create(
            team=self.team,
            query={
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    "breakdownFilter": {"breakdown_type": "cohort", "breakdown": [cohort_a.id]},
                },
            },
        )
        insight_b = Insight.objects.create(
            team=self.team,
            filters={
                "events": [{"id": "$pageview"}],
                "properties": [{"key": "id", "value": cohort_b.id, "type": "cohort"}],
            },
        )
        DashboardTile.objects.create(dashboard=dashboard, insight=insight_a)
        DashboardTile.objects.create(dashboard=dashboard, insight=insight_b)

        config = SharingConfiguration.objects.create(team=self.team, dashboard=dashboard, enabled=True)
        response = self.client.get(f"/shared/{config.access_token}")
        assert response.status_code == 200

        exported_cohorts = self._parse_exported_cohorts(response.content.decode())
        assert sorted(exported_cohorts, key=lambda c: c["id"]) == sorted(
            [{"id": cohort_a.id, "name": "Cohort A"}, {"id": cohort_b.id, "name": "Cohort B"}],
            key=lambda c: c["id"],
        )

    @staticmethod
    def _parse_exported_data(html: str) -> dict:
        # mock_exporter_template embeds the exported_data JSON inside this <script> tag.
        start_marker = '<script id="posthog-exported-data" type="application/json">'
        start = html.index(start_marker) + len(start_marker)
        end = html.index("</script>", start)
        outer = json.loads(html[start:end])
        inner = json.loads(outer) if isinstance(outer, str) else outer
        return inner

    @staticmethod
    def _parse_exported_cohorts(html: str) -> list[dict]:
        return TestSharedCohortInlining._parse_exported_data(html).get("cohorts", [])

    @mock_exporter_template
    def test_shared_dashboard_includes_widget_metadata_only(self):
        dashboard = Dashboard.objects.create(team=self.team, name="dash", created_by=self.user)
        widget = DashboardWidget.all_teams.create(
            team_id=self.team.id,
            widget_type="error_tracking_list",
            name="Top errors",
            config={"limit": 10},
            created_by=self.user,
            last_modified_by=self.user,
        )
        DashboardTile.objects.create(
            dashboard=dashboard,
            team_id=self.team.id,
            widget=widget,
            layouts={"sm": {"x": 0, "y": 0, "w": 6, "h": 5}},
        )

        config = SharingConfiguration.objects.create(team=self.team, dashboard=dashboard, enabled=True)
        response = self.client.get(f"/shared/{config.access_token}")
        assert response.status_code == 200

        exported = self._parse_exported_data(response.content.decode())
        widget_tiles = [tile for tile in exported["dashboard"]["tiles"] if tile.get("widget")]
        assert len(widget_tiles) == 1

        widget_data = widget_tiles[0]["widget"]
        assert set(widget_data.keys()) == {"id", "widget_type", "name", "description", "config"}
        assert widget_data["widget_type"] == "error_tracking_list"
        assert widget_data["config"]["limit"] == 10
        assert "created_by" not in widget_data


class TestSharingResourceEditChecks(APIBaseTest):
    def test_every_shareable_resource_has_an_edit_check(self):
        assert set(SHARING_RESOURCE_EDIT_CHECKS) == SharingConfiguration.shareable_resource_fields()

    @parameterized.expand(
        [
            ("a shareable resource has no registered edit check", "recording", None),
            ("the registry references a non-existent field", None, "made_up_resource"),
        ]
    )
    def test_assertion_rejects_a_registry_out_of_sync_with_the_model(self, _name, drop_key, add_key):
        mutated = dict(SHARING_RESOURCE_EDIT_CHECKS)
        if drop_key:
            mutated.pop(drop_key)
        if add_key:
            mutated[add_key] = None

        with patch.dict("posthog.api.sharing.SHARING_RESOURCE_EDIT_CHECKS", mutated, clear=True):
            with self.assertRaises(ImproperlyConfigured):
                _assert_every_shareable_resource_is_gated()

    @patch("posthog.api.sharing.UserAccessControl")
    def test_gate_fails_closed_for_a_resource_with_no_edit_check(self, _mock_user_access_control):
        sharing = Mock(spec=SharingConfiguration)
        for field_name in SharingConfiguration.shareable_resource_fields():
            setattr(sharing, field_name, None)
        sharing.interviewee_context = Mock()
        sharing.team = self.team

        request = Mock(method="PATCH", data={})
        request.user = self.user
        view = Mock(team=self.team)

        with self.assertRaises(PermissionDenied) as caught:
            check_can_edit_sharing_configuration(view, request, sharing)

        assert "cannot be shared through this endpoint" in str(caught.exception)


def _warehouse_ac_flag(key: str, *args, **kwargs) -> bool:
    return key == "hogql-warehouse-access-control"


@patch("posthoganalytics.feature_enabled", new=Mock(side_effect=_warehouse_ac_flag))
class TestSharedLinkWarehouseExecution(APIBaseTest):
    def setUp(self):
        super().setUp()
        from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="governed_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"},
            columns={"id": "String"},
        )
        self.insight = Insight.objects.create(
            team=self.team,
            query={
                "kind": "DataTableNode",
                "source": {"kind": "HogQLQuery", "query": "SELECT id FROM governed_view"},
            },
            created_by=self.user,
        )
        self.client.logout()

    def test_shared_insight_over_warehouse_executes_via_token_api(self):
        config = SharingConfiguration.objects.create(team=self.team, insight=self.insight, enabled=True)

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/{self.insight.id}/"
            f"?sharing_access_token={config.access_token}&refresh=blocking"
        )

        # Warehouse-backed shared insight executes (AC bypassed) instead of failing closed userless.
        assert response.status_code == status.HTTP_200_OK, response.content
        assert not response.json().get("result_error")

    def test_shared_dashboard_page_refresh_computes_warehouse_tile(self):
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        DashboardTile.objects.create(dashboard=dashboard, insight=self.insight)
        config = SharingConfiguration.objects.create(team=self.team, dashboard=dashboard, enabled=True)

        # The /shared/ page normally serves cached results and refreshes them async; refresh=blocking
        # is the only flow that executes the query during this request. That execution runs as the
        # shared-link user from the page context - if that wiring breaks, it runs userless and fails closed.
        response = self.client.get(f"/shared/{config.access_token}.json?refresh=blocking")

        assert response.status_code == status.HTTP_200_OK, response.content
        tiles = response.json()["dashboard"]["tiles"]
        assert len(tiles) == 1
        assert tiles[0]["insight"]["result"], tiles[0]["insight"].get("result_error")

    def test_shared_notebook_inline_warehouse_query_executes(self):
        from products.notebooks.backend.models import Notebook

        notebook = Notebook.objects.create(
            team=self.team,
            created_by=self.user,
            content={
                "type": "doc",
                "content": [
                    {
                        "type": "ph-query",
                        "attrs": {
                            "nodeId": "wh",
                            "query": {
                                "kind": "DataTableNode",
                                "source": {"kind": "HogQLQuery", "query": "SELECT id FROM governed_view"},
                            },
                        },
                    }
                ],
            },
        )
        config = SharingConfiguration.objects.create(team=self.team, notebook=notebook, enabled=True)

        response = self.client.get(f"/shared/{config.access_token}.json")

        assert response.status_code == status.HTTP_200_OK, response.content
        results = response.json().get("inline_query_results", {})
        assert "wh" in results
        assert not results["wh"].get("error")


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestSharingPublishGate(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="governed_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"},
            columns={"id": "String"},
        )
        self.insight = Insight.objects.create(
            team=self.team,
            query={
                "kind": "DataTableNode",
                "source": {"kind": "HogQLQuery", "query": "SELECT id FROM governed_view"},
            },
            created_by=self.user,
        )

    def _deny_warehouse(self) -> None:

        AccessControl.objects.create(team=self.team, resource="warehouse_objects", access_level="none")

    def _enable_sharing(self, kind: str):
        if kind == "insight":
            url = f"/api/projects/{self.team.id}/insights/{self.insight.id}/sharing"
        elif kind == "dashboard":
            dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
            DashboardTile.objects.create(dashboard=dashboard, insight=self.insight)
            url = f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing"
        else:
            notebook = Notebook.objects.create(
                team=self.team,
                created_by=self.user,
                content={
                    "type": "doc",
                    "content": [
                        {
                            "type": "ph-query",
                            "attrs": {
                                "nodeId": "wh",
                                "query": {
                                    "kind": "DataTableNode",
                                    "source": {"kind": "HogQLQuery", "query": "SELECT id FROM governed_view"},
                                },
                            },
                        }
                    ],
                },
            )
            url = f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/sharing"
        return self.client.patch(url, {"enabled": True})

    @parameterized.expand([("insight",), ("dashboard",), ("notebook",)])
    def test_denied_publisher_cannot_enable_sharing(self, kind: str):
        self._deny_warehouse()

        response = self._enable_sharing(kind)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "Can't enable sharing" in str(response.json())
        assert "governed_view" in str(response.json())
        assert not SharingConfiguration.objects.filter(team=self.team, enabled=True).exists()

    def test_publisher_with_access_can_enable_sharing(self):
        response = self._enable_sharing("dashboard")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["enabled"] is True

    def test_system_table_denial_blocks_publishing(self):

        AccessControl.objects.create(team=self.team, resource="dashboard", access_level="none")
        self.insight.query = {
            "kind": "DataTableNode",
            "source": {"kind": "HogQLQuery", "query": "SELECT id FROM system.dashboards"},
        }
        self.insight.save()

        response = self._enable_sharing("insight")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "system.dashboards" in str(response.json())

    @parameterized.expand([("denied",), ("allowed",)])
    def test_runner_level_resource_access_gates_publishing(self, case: str):
        # AccountsQuery enforces access in validate_query_runner_access (resource level),
        # not per-table - the compile check alone is blind to it.
        self.insight.query = {"kind": "AccountsQuery"}
        self.insight.save()
        if case == "denied":
            AccessControl.objects.create(team=self.team, resource="customer_analytics", access_level="none")

        response = self._enable_sharing("insight")

        if case == "denied":
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
            assert "customer_analytics" in str(response.json())
            assert not SharingConfiguration.objects.filter(team=self.team, enabled=True).exists()
        else:
            assert response.status_code == status.HTTP_200_OK, response.content

    def test_already_enabled_share_is_not_regated(self):
        config = SharingConfiguration.objects.create(team=self.team, insight=self.insight, enabled=True)
        self._deny_warehouse()

        # Not an enable transition: settings edits on an already-published share stay possible
        # even if the editor has since lost access to the underlying tables.
        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{self.insight.id}/sharing",
            {"enabled": True, "settings": {"whitelabel": True}},
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        config.refresh_from_db()
        assert config.enabled is True

    @parameterized.expand([("non_materialized",), ("materialized",)])
    def test_granted_view_over_denied_table_gates_unless_materialized(self, case: str):

        inner = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="restricted_inner",
            query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"},
            columns={"id": "String"},
        )
        outer = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="safe_view",
            query={"kind": "HogQLQuery", "query": "SELECT id FROM restricted_inner"},
            columns={"id": "String"},
        )
        AccessControl.objects.create(
            team=self.team, resource="warehouse_view", resource_id=str(inner.id), access_level="none"
        )
        self.insight.query = {
            "kind": "DataTableNode",
            "source": {"kind": "HogQLQuery", "query": "SELECT id FROM safe_view"},
        }
        self.insight.save()
        if case == "materialized":
            from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

            credential = DataWarehouseCredential.objects.create(access_key="k", access_secret="s", team=self.team)
            backing = DataWarehouseTable.objects.create(
                name=outer.name,
                format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
                team=self.team,
                credential=credential,
                url_pattern=outer.url_pattern,
                columns={"id": "String"},
            )
            outer.table = backing
            outer.is_materialized = True
            outer.save(update_fields=["table", "is_materialized"])

        response = self._enable_sharing("insight")

        if case == "materialized":
            # A granted materialized view resolves to its backing table - the recommended
            # "grant safe views" setup stays publishable.
            assert response.status_code == status.HTTP_200_OK, response.content
        else:
            # A non-materialized view re-resolves through its underlying tables, exactly like
            # the publisher's own in-app run - so it can't be published either. This is the
            # compile-vs-name-level distinction: a name-level check would let this through.
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
            assert "restricted_inner" in str(response.json())

    def test_unparseable_query_does_not_block_publishing(self):
        self._deny_warehouse()
        self.insight.query = {
            "kind": "DataTableNode",
            "source": {"kind": "HogQLQuery", "query": "SELECT FROM WHERE ((("},
        }
        self.insight.save()

        # A broken query errors for everyone at view time - that's not an access problem,
        # so it must not block publishing.
        response = self._enable_sharing("insight")

        assert response.status_code == status.HTTP_200_OK, response.content


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestSaveTimeAccessBlock(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="governed_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"},
            columns={"id": "String"},
        )
        self.insight = Insight.objects.create(
            team=self.team,
            query={"kind": "DataTableNode", "source": {"kind": "HogQLQuery", "query": "SELECT 1 AS one"}},
            created_by=self.user,
        )

    def _deny_editor(self) -> None:
        AccessControl.objects.create(team=self.team, resource="warehouse_objects", access_level="none")

    _DENIED_QUERY = {"kind": "DataTableNode", "source": {"kind": "HogQLQuery", "query": "SELECT id FROM governed_view"}}

    def _patch_insight_query(self):
        return self.client.patch(
            f"/api/projects/{self.team.id}/insights/{self.insight.id}/", {"query": self._DENIED_QUERY}
        )

    @parameterized.expand([("direct",), ("dashboard",), ("notebook",)])
    def test_query_update_blocked_when_insight_is_publicly_shared(self, coverage: str):
        self._deny_editor()
        if coverage == "direct":
            SharingConfiguration.objects.create(team=self.team, insight=self.insight, enabled=True)
        elif coverage == "dashboard":
            dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
            DashboardTile.objects.create(dashboard=dashboard, insight=self.insight)
            SharingConfiguration.objects.create(team=self.team, dashboard=dashboard, enabled=True)
        else:
            notebook = Notebook.objects.create(
                team=self.team,
                created_by=self.user,
                content={
                    "type": "doc",
                    "content": [
                        {
                            "type": "ph-query",
                            "attrs": {
                                "nodeId": "e1",
                                "query": {"kind": "SavedInsightNode", "shortId": self.insight.short_id},
                            },
                        }
                    ],
                },
            )
            SharingConfiguration.objects.create(team=self.team, notebook=notebook, enabled=True)

        response = self._patch_insight_query()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "publicly shared" in str(response.json())
        self.insight.refresh_from_db()
        assert self.insight.query == {
            "kind": "DataTableNode",
            "source": {"kind": "HogQLQuery", "query": "SELECT 1 AS one"},
        }

    def test_query_update_allowed_when_not_shared(self):
        self._deny_editor()

        response = self._patch_insight_query()

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_adding_insight_to_shared_dashboard_blocked(self):
        self._deny_editor()
        self.insight.query = self._DENIED_QUERY
        self.insight.save()
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        SharingConfiguration.objects.create(team=self.team, dashboard=dashboard, enabled=True)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{self.insight.id}/", {"dashboards": [dashboard.id]}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "publicly shared" in str(response.json())
        assert not DashboardTile.objects.filter(dashboard=dashboard, insight=self.insight).exists()

    def test_adding_insight_to_unshared_dashboard_allowed(self):
        self._deny_editor()
        self.insight.query = self._DENIED_QUERY
        self.insight.save()
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{self.insight.id}/", {"dashboards": [dashboard.id]}
        )

        assert response.status_code == status.HTTP_200_OK, response.content

    def _shared_notebook(self, content: dict) -> Notebook:
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, content=content, version=1)
        SharingConfiguration.objects.create(team=self.team, notebook=notebook, enabled=True)
        return notebook

    def _patch_notebook_content(self, notebook: Notebook, content: dict):
        return self.client.patch(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/",
            {"content": content, "version": notebook.version},
        )

    @parameterized.expand(
        [
            ("inline_query", {"kind": "HogQLQuery", "query": "SELECT id FROM governed_view"}),
            ("incomplete_query", {"kind": "HogQLQuery", "query": "SELECT FROM WHERE ((("}),
        ]
    )
    def test_notebook_edit_adding_inline_query(self, case: str, source: dict):
        self._deny_editor()
        notebook = self._shared_notebook({"type": "doc", "content": []})
        new_content = {
            "type": "doc",
            "content": [
                {
                    "type": "ph-query",
                    "attrs": {"nodeId": "n1", "query": {"kind": "DataTableNode", "source": source}},
                }
            ],
        }

        response = self._patch_notebook_content(notebook, new_content)

        if case == "inline_query":
            # A publicly shared notebook must not accept queries the editor can't run.
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
            assert "publicly shared" in str(response.json())
        else:
            # Broken mid-typing content isn't an access problem - autosave keeps flowing.
            assert response.status_code == status.HTTP_200_OK, response.content

    def test_notebook_edit_untouched_denied_query_does_not_gate(self):
        self._deny_editor()
        denied_node = {
            "type": "ph-query",
            "attrs": {
                "nodeId": "n1",
                "query": {
                    "kind": "DataTableNode",
                    "source": {"kind": "HogQLQuery", "query": "SELECT id FROM governed_view"},
                },
            },
        }
        notebook = self._shared_notebook({"type": "doc", "content": [denied_node]})
        # Only the edit's delta is checked - pre-existing content never re-gates an autosave.
        new_content = {"type": "doc", "content": [denied_node, {"type": "paragraph"}]}

        response = self._patch_notebook_content(notebook, new_content)

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_notebook_collab_save_blocked_for_denied_query(self):
        # Collab saves write content directly (not through NotebookSerializer.update), so the
        # guard must exist on that path too - otherwise collab-enabled notebooks bypass the gate.
        self._deny_editor()
        notebook = self._shared_notebook({"type": "doc", "content": []})
        new_content = {
            "type": "doc",
            "content": [
                {
                    "type": "ph-query",
                    "attrs": {
                        "nodeId": "n1",
                        "query": {
                            "kind": "DataTableNode",
                            "source": {"kind": "HogQLQuery", "query": "SELECT id FROM governed_view"},
                        },
                    },
                }
            ],
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/collab/save/",
            data={"client_id": "c1", "version": notebook.version, "steps": [], "content": new_content},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "publicly shared" in str(response.json())
        notebook.refresh_from_db()
        assert notebook.content == {"type": "doc", "content": []}

    def test_notebook_markdown_save_blocked_for_denied_query(self):
        # The markdown editor autosaves through collab/markdown_save, a third write path that also
        # persists content directly - without the guard here, markdown notebooks bypass the gate.
        self._deny_editor()
        notebook = self._shared_notebook({"type": "doc", "content": []})
        denied_query = {
            "kind": "DataTableNode",
            "source": {"kind": "HogQLQuery", "query": "SELECT id FROM governed_view"},
        }
        new_content = {
            "type": "doc",
            "content": [
                {
                    "type": "ph-markdown-notebook",
                    "attrs": {
                        "nodeId": "markdown-notebook-v2",
                        "markdown": '<Query nodeId="q1" query={' + json.dumps(denied_query) + "} />",
                    },
                }
            ],
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/collab/markdown_save/",
            data={"client_id": "c1", "version": notebook.version, "content": new_content, "text_content": ""},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "publicly shared" in str(response.json())
        notebook.refresh_from_db()
        assert notebook.content == {"type": "doc", "content": []}

    def test_notebook_embedding_denied_insight_blocked(self):
        self._deny_editor()
        self.insight.query = self._DENIED_QUERY
        self.insight.save()
        notebook = self._shared_notebook({"type": "doc", "content": []})
        new_content = {
            "type": "doc",
            "content": [
                {
                    "type": "ph-query",
                    "attrs": {
                        "nodeId": "e1",
                        "query": {"kind": "SavedInsightNode", "shortId": self.insight.short_id},
                    },
                }
            ],
        }

        response = self._patch_notebook_content(notebook, new_content)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "publicly shared" in str(response.json())
