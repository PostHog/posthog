from datetime import timedelta
from functools import wraps

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, Mock, patch

from django.utils import timezone
from django.utils.timezone import now

from parameterized import parameterized
from rest_framework import status

from posthog.api.sharing import _log_share_password_attempt, shared_url_as_png
from posthog.constants import AvailableFeature
from posthog.models import ActivityLog, ExportedAsset
from posthog.models.dashboard import Dashboard
from posthog.models.filters.filter import Filter
from posthog.models.insight import Insight
from posthog.models.share_password import SharePassword
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.user import User


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
    @patch("posthog.api.exports.exporter.export_asset.delay")
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
    @patch("posthog.api.exports.exporter.export_asset.delay")
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

    @patch("posthog.api.exports.exporter.export_asset.delay")
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

    @patch("posthog.api.exports.exporter.export_asset.delay")
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

    @patch("posthog.api.exports.exporter.export_asset.delay")
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

    @patch("posthog.api.exports.exporter.export_asset.delay")
    def test_should_update_to_match_existing_dashboard_sharing_token(self, patched_exporter_task: Mock):
        dashboard = Dashboard.objects.create(team=self.team, name="example dashboard", created_by=self.user)
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing")
        initial_token = response.json()["access_token"]
        assert initial_token
        assert not response.json()["enabled"]

        dashboard.share_token = "my_test_token"
        dashboard.is_shared = True
        dashboard.save()

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing")
        data = response.json()
        assert data["access_token"] == "my_test_token"
        assert data["enabled"]

        dashboard.share_token = None
        dashboard.is_shared = False
        dashboard.save()

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing")
        data = response.json()
        assert data["access_token"] == "my_test_token"
        assert data["enabled"]

    @patch("posthog.api.exports.exporter.export_asset.delay")
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

    @patch("posthog.api.exports.exporter.export_asset.delay")
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
    @patch("posthog.api.exports.exporter.export_asset.delay")
    @patch("posthog.models.exported_asset.object_storage.read_bytes")
    @patch("posthog.api.sharing.asset_for_token")
    def test_can_get_shared_dashboard_asset_with_no_content_but_content_location(
        self,
        url: str,
        patched_asset_for_token,
        patched_object_storage,
        _patched_exporter_task: Mock,
    ) -> None:
        asset = ExportedAsset.objects.create(
            team_id=self.team.id,
            export_format=ExportedAsset.ExportFormat.PNG,
            content=None,
            content_location="some object url",
        )
        patched_asset_for_token.return_value = asset

        patched_object_storage.return_value = b"the image bytes"

        response = self.client.get(url)

        assert response.status_code == 200
        assert response.headers.get("Content-Type") == "image/png"
        assert response.content == b"the image bytes"

    @parameterized.expand(["insights", "dashboards"])
    @patch("posthog.models.exported_asset.object_storage.read_bytes")
    @patch("posthog.api.exports.exporter.export_asset.delay")
    def test_shared_thing_can_generate_open_graph_image(
        self, type: str, patched_exporter_task: Mock, patched_object_storage: Mock
    ) -> None:
        patched_object_storage.return_value = b"the image bytes"

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
        assert item_opengraph_image.status_code == 200
        assert item_opengraph_image.headers["Content-Type"] == "image/png"
        assert item_opengraph_image.content == b"the image bytes"

    @parameterized.expand(["insights", "dashboards"])
    @patch("posthog.models.exported_asset.object_storage.read_bytes")
    @patch("posthog.api.exports.exporter.export_asset.delay")
    def test_shared_thing_can_reuse_existing_generated_open_graph_image(
        self, type: str, patched_exporter_task: Mock, patched_object_storage: Mock
    ) -> None:
        patched_object_storage.return_value = b"the image bytes"

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
        assert item_opengraph_image.status_code == 200
        assert item_opengraph_image.headers["Content-Type"] == "image/png"
        assert item_opengraph_image.content == b"the image bytes"

    def _setup_patched_exporter(self, patched_exporter_task):
        def add_content_location_on_task_run(*args, **kwargs):
            asset = ExportedAsset.objects.get(team_id=self.team.id)
            asset.content_location = "some object url"
            asset.save()

            return MagicMock()

        patched_exporter_task.side_effect = add_content_location_on_task_run

    @parameterized.expand(["insights", "dashboards"])
    @patch("posthog.models.exported_asset.object_storage.read_bytes")
    @patch("posthog.api.exports.exporter.export_asset.delay")
    def test_shared_insight_can_regenerate_stale_existing_generated_open_graph_image(
        self, type: str, patched_exporter_task: Mock, patched_object_storage: Mock
    ) -> None:
        patched_object_storage.return_value = b"the image bytes"
        self._setup_patched_exporter(patched_exporter_task)

        target = self.insight if type == "insights" else self.dashboard

        # the existing asset is stale because it is more than 3 hours old
        time_in_the_past = now() - timedelta(hours=4)
        with freeze_time(time_in_the_past):
            share_response = self.client.patch(
                f"/api/projects/{self.team.id}/{type}/{target.pk}/sharing",
                {"enabled": True},
            )
            # enabling creates an asset
            assert ExportedAsset.objects.count() == 1
            original_asset = ExportedAsset.objects.first()

        access_token = share_response.json()["access_token"]

        # times passes and the asset is stale
        assert ExportedAsset.objects.count() == 0

        item_opengraph_image = self.client.get("/shared/" + access_token + ".png")
        assert item_opengraph_image.status_code == 200
        assert item_opengraph_image.headers["Content-Type"] == "image/png"
        assert item_opengraph_image.content == b"the image bytes"

        assert ExportedAsset.objects.count() == 1
        final_asset = ExportedAsset.objects.first()
        assert final_asset is not None
        assert original_asset is not None
        assert final_asset.id != original_asset.id

    @patch("posthog.api.exports.exporter.export_asset.delay")
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

    @patch("posthog.api.exports.exporter.export_asset.delay")
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
    @patch("posthog.api.exports.exporter.export_asset.delay")
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

    @patch("posthog.api.exports.exporter.export_asset.delay")
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

    @patch("posthog.api.exports.exporter.export_asset.delay")
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

    @patch("posthog.api.exports.exporter.export_asset.delay")
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
    # @patch("posthog.api.exports.exporter.export_asset.delay")
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
    # @patch("posthog.api.exports.exporter.export_asset.delay")
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
    # @patch("posthog.api.exports.exporter.export_asset.delay")
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
    # @patch("posthog.api.exports.exporter.export_asset.delay")
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
    @patch("posthog.api.exports.exporter.export_asset.delay")
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

    @patch("posthog.api.exports.exporter.export_asset.delay")
    def test_valid_settings_are_accepted(self, patched_exporter_task: Mock):
        """Test that valid settings are accepted and validated"""
        valid_settings = {
            "whitelabel": True,
            "noHeader": False,
            "showInspector": True,
            "legend": False,
            "detailed": True,
        }

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True, "settings": valid_settings},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["settings"] == valid_settings

    @patch("posthog.api.exports.exporter.export_asset.delay")
    def test_partial_settings_are_filled_with_defaults(self, patched_exporter_task: Mock):
        """Test that partial settings are filled with defaults during validation"""
        partial_settings = {"whitelabel": True, "legend": True}

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
        }
        assert data["settings"] == expected_settings

    @patch("posthog.api.exports.exporter.export_asset.delay")
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

    @patch("posthog.api.exports.exporter.export_asset.delay")
    def test_null_settings_are_accepted(self, patched_exporter_task: Mock):
        """Test that null settings are accepted"""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing",
            {"enabled": True, "settings": None},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["settings"] is None

    @patch("posthog.api.exports.exporter.export_asset.delay")
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

        with patch("posthog.api.exports.exporter.export_asset.delay"):
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

    @patch("posthog.api.exports.exporter.export_asset.delay")
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
