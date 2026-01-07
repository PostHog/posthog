from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import mock_open, patch

from boto3 import resource
from botocore.client import Config

from posthog.api.insight_variable import map_stale_to_latest
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Dashboard, ExportedAsset, Insight, InsightVariable
from posthog.models.dashboard_tile import DashboardTile
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError
from posthog.tasks.exports import image_exporter

TEST_PREFIX = "Test-Exports"


@patch("posthog.tasks.exports.image_exporter._screenshot_asset")
@patch(
    "posthog.tasks.exports.image_exporter.open",
    new_callable=mock_open,
    read_data=b"image_data",
)
@patch("os.remove")
class TestImageExporter(APIBaseTest):
    exported_asset: ExportedAsset

    def setup_method(self, method):
        insight = Insight.objects.create(team=self.team)
        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            insight=insight,
        )
        self.exported_asset = asset

    def teardown_method(self, method):
        s3 = resource(
            "s3",
            endpoint_url=OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        bucket = s3.Bucket(OBJECT_STORAGE_BUCKET)
        bucket.objects.filter(Prefix=TEST_PREFIX).delete()

    def test_image_exporter_writes_to_asset_when_object_storage_is_disabled(self, *args) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=False):
            image_exporter.export_image(self.exported_asset)

            assert self.exported_asset.content == b"image_data"
            assert self.exported_asset.content_location is None

    @patch("posthog.models.exported_asset.UUIDT")
    def test_image_exporter_writes_to_object_storage_when_object_storage_is_enabled(self, mocked_uuidt, *args) -> None:
        mocked_uuidt.return_value = "a-guid"
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_EXPORTS_FOLDER="Test-Exports"):
            image_exporter.export_image(self.exported_asset)

            assert (
                self.exported_asset.content_location
                == f"{TEST_PREFIX}/png/team-{self.team.id}/task-{self.exported_asset.id}/a-guid"
            )

            content = object_storage.read_bytes(self.exported_asset.content_location)
            assert content == b"image_data"

            assert self.exported_asset.content is None

    @patch("posthog.models.exported_asset.UUIDT")
    @patch("posthog.models.exported_asset.object_storage.write")
    def test_image_exporter_writes_to_object_storage_when_object_storage_write_fails(
        self, mocked_object_storage_write, mocked_uuidt, *args
    ) -> None:
        mocked_uuidt.return_value = "a-guid"
        mocked_object_storage_write.side_effect = ObjectStorageError("mock write failed")

        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_EXPORTS_FOLDER="Test-Exports"):
            image_exporter.export_image(self.exported_asset)

            assert self.exported_asset.content_location is None

            assert self.exported_asset.content == b"image_data"

    @patch("posthog.tasks.exports.image_exporter.process_query_dict")
    def test_dashboard_export_calculates_all_insights(self, mock_process_query: Any, *args: Any) -> None:
        mock_process_query.return_value = {"cache_key": "test_cache_key", "result": []}

        dashboard = Dashboard.objects.create(team=self.team, name="Test Dashboard")
        insight_count = 3

        insights = []
        for i in range(insight_count):
            insight = Insight.objects.create(
                team=self.team,
                name=f"SQL Insight {i}",
                query={
                    "kind": "DataVisualizationNode",
                    "source": {"kind": "HogQLQuery", "query": f"SELECT {i} as value"},
                },
            )
            insights.append(insight)
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        dashboard_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            dashboard=dashboard,
            insight=None,
        )

        with self.settings(OBJECT_STORAGE_ENABLED=False):
            image_exporter.export_image(dashboard_asset)

        assert mock_process_query.call_count == insight_count, (
            f"Expected cache warming for {insight_count} insights, got {mock_process_query.call_count} calls"
        )

        for i, call in enumerate(mock_process_query.call_args_list):
            call_kwargs = call[1]

            assert call_kwargs["dashboard_id"] == dashboard.id, f"Call {i + 1} missing dashboard_id"

            assert call_kwargs["execution_mode"] == ExecutionMode.CALCULATE_BLOCKING_ALWAYS, (
                f"Call {i + 1} should use CALCULATE_BLOCKING_ALWAYS, got {call_kwargs['execution_mode']}"
            )

            assert call_kwargs["insight_id"] in [ins.id for ins in insights], (
                f"Call {i + 1} has unexpected insight_id {call_kwargs['insight_id']}"
            )

    @patch("posthog.tasks.exports.image_exporter.process_query_dict")
    def test_export_captures_cache_keys_and_passes_to_url(
        self,
        mock_process_query: Any,
        mock_remove: Any,
        mock_open: Any,
        mock_screenshot_asset: Any,
    ) -> None:
        """Test that cache keys from warming are captured and passed to the screenshot URL."""
        insight = Insight.objects.create(
            team=self.team,
            name="Test Insight",
            query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "SELECT 1 as value"}},
        )
        exported_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            insight=insight,
        )

        mock_process_query.return_value = {"cache_key": "test_cache_key_123", "results": []}

        with self.settings(OBJECT_STORAGE_ENABLED=False):
            image_exporter.export_image(exported_asset)

        # Verify _screenshot_asset was called with a URL containing cache_keys
        assert mock_screenshot_asset.called
        call_args = mock_screenshot_asset.call_args
        url_to_render = call_args[0][1]  # Second positional arg is the URL

        assert "cache_keys=" in url_to_render, f"URL should contain cache_keys parameter: {url_to_render}"
        assert "test_cache_key_123" in url_to_render, f"URL should contain the cache key: {url_to_render}"

    @patch("posthog.tasks.exports.image_exporter.process_query_dict")
    def test_dashboard_export_captures_all_cache_keys(
        self,
        mock_process_query: Any,
        mock_remove: Any,
        mock_open: Any,
        mock_screenshot_asset: Any,
    ) -> None:
        """Test that cache keys for all insights in a dashboard are captured and passed to URL."""
        dashboard = Dashboard.objects.create(team=self.team, name="Test Dashboard")

        insights = []
        for i in range(3):
            insight = Insight.objects.create(
                team=self.team,
                name=f"Insight {i}",
                query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": f"SELECT {i}"}},
            )
            insights.append(insight)
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        dashboard_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            dashboard=dashboard,
        )

        def mock_process(team: Any, query: Any, insight_id: Any = None, **kwargs: Any) -> dict:
            return {"cache_key": f"cache_key_for_insight_{insight_id}", "results": []}

        mock_process_query.side_effect = mock_process

        with self.settings(OBJECT_STORAGE_ENABLED=False):
            image_exporter.export_image(dashboard_asset)

        # Verify _screenshot_asset was called with URL containing all cache keys
        assert mock_screenshot_asset.called
        url_to_render = mock_screenshot_asset.call_args[0][1]

        # URL should contain cache_keys for all insights
        for insight in insights:
            assert f"cache_key_for_insight_{insight.id}" in url_to_render, (
                f"URL should contain cache key for insight {insight.id}"
            )

    @patch("posthog.tasks.exports.image_exporter._screenshot_asset")
    @patch("posthog.tasks.exports.image_exporter.open", new_callable=mock_open, read_data=b"image_data")
    @patch("os.remove")
    def test_export_includes_dashboard_variables(self, *args: Any) -> None:
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Test Dashboard with Variables",
            variables={"test_var": {"id": "var_123", "name": "test_var", "type": "String", "default": "value1"}},
        )

        InsightVariable.objects.create(team=self.team, name="test_var", type="String", default_value="value1")

        insight = Insight.objects.create(
            team=self.team,
            name="Test Insight",
            query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "SELECT 1 as value"}},
        )
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        exported_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            dashboard=dashboard,
            insight=insight,
        )

        with patch("posthog.tasks.exports.image_exporter.process_query_dict") as mock_process_query:
            mock_process_query.return_value = {"cache_key": "test_key", "results": []}

            with self.settings(OBJECT_STORAGE_ENABLED=False):
                image_exporter.export_image(exported_asset)

            assert mock_process_query.call_count == 1
            call_kwargs = mock_process_query.call_args[1]

            assert "variables_override_json" in call_kwargs, "variables_override_json parameter missing"
            assert call_kwargs["variables_override_json"] is not None, (
                "variables_override_json should not be None when dashboard has variables"
            )

            variables = list(InsightVariable.objects.filter(team=self.team).all())
            expected_variables = map_stale_to_latest(dashboard.variables or {}, variables)
            assert call_kwargs["variables_override_json"] == expected_variables, (
                "variables_override_json should match the transformed dashboard variables"
            )
