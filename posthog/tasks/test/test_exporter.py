import base64
from typing import Optional

import pytest
from posthog.test.base import APIBaseTest
from unittest import TestCase
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.hogql.errors import QueryError

from posthog.errors import CHQueryErrorTooManySimultaneousQueries
from posthog.models.dashboard import Dashboard
from posthog.models.exported_asset import ExportedAsset
from posthog.tasks import exporter
from posthog.tasks.exporter import _is_final_export_attempt
from posthog.tasks.exports.image_exporter import get_driver


class MockWebDriver(MagicMock):
    def find_element_by_css_selector(self, name: str) -> Optional[MagicMock]:
        return MagicMock()  # Always return something for wait_for_css_selector

    def find_element_by_class_name(self, name: str) -> Optional[MagicMock]:
        return None  # Never return anything for Spinner


@patch("posthog.tasks.exports.image_exporter.uuid")
class TestExporterTask(APIBaseTest):
    exported_asset: ExportedAsset = None  # type: ignore

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        dashboard = Dashboard.objects.create(team=cls.team, name="example dashboard", created_by=cls.user)
        cls.exported_asset = ExportedAsset.objects.create(
            team=cls.team, dashboard_id=dashboard.id, export_format="image/png"
        )

        example_png = b"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"

        with open("/tmp/posthog_test_exporter.png", "wb") as fh:
            fh.write(base64.decodebytes(example_png))

    @patch("posthog.tasks.exports.image_exporter.get_driver")
    def test_exporter_runs(self, mock_get_driver: MagicMock, mock_uuid: MagicMock) -> None:
        mock_uuid.uuid4.return_value = "posthog_test_exporter"
        mock_get_driver.return_value = MockWebDriver()

        assert self.exported_asset.content is None
        assert self.exported_asset.content_location is None

        exporter.export_asset(self.exported_asset.id)
        self.exported_asset.refresh_from_db()

        assert self.exported_asset.content is None
        assert self.exported_asset.content_location is not None

    @pytest.mark.skip("Currently broken due to an issue with ChromeDriver")
    def test_exporter_setsup_selenium(self, mock_uuid: MagicMock) -> None:
        driver = get_driver()

        assert driver is not None

        driver.get("https://example.com")

        if driver:
            driver.close()


class TestIsFinalExportAttempt(TestCase):
    @parameterized.expand(
        [
            # Non-retriable exceptions are always final (regardless of retry count)
            (QueryError("test"), 0, 3, True),
            (QueryError("test"), 1, 3, True),
            (QueryError("test"), 3, 3, True),
            # Retriable exceptions: not final when retries < max_retries
            (CHQueryErrorTooManySimultaneousQueries("test"), 0, 3, False),
            (CHQueryErrorTooManySimultaneousQueries("test"), 1, 3, False),
            (CHQueryErrorTooManySimultaneousQueries("test"), 2, 3, False),
            # Retriable exceptions: final when retries >= max_retries
            (CHQueryErrorTooManySimultaneousQueries("test"), 3, 3, True),
            (CHQueryErrorTooManySimultaneousQueries("test"), 4, 3, True),
        ]
    )
    def test_is_final_export_attempt(
        self, exception: Exception, current_retries: int, max_retries: int, expected: bool
    ) -> None:
        assert _is_final_export_attempt(exception, current_retries, max_retries) == expected


class TestExportAssetFailureRecording(APIBaseTest):
    """Tests for failure recording behavior in export_asset task."""

    @patch("posthog.tasks.exporter.export_asset_direct")
    def test_non_retriable_error_records_failure_and_does_not_raise(self, mock_export_direct: MagicMock) -> None:
        """
        Test that non-retriable errors (like QueryError) record failure info
        and do NOT re-raise the exception (swallowed to align with previous behavior).
        """
        mock_export_direct.side_effect = QueryError("Invalid query syntax")

        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
        )

        # Should NOT raise - non-retriable errors are swallowed
        exporter.export_asset(asset.id)

        asset.refresh_from_db()
        assert asset.exception == "Invalid query syntax"
        assert asset.exception_type == "QueryError"
        assert asset.failure_type == "user"

    @patch("posthog.tasks.exporter.export_asset_direct")
    def test_retriable_error_raises_and_does_not_record_on_non_final_attempt(
        self, mock_export_direct: MagicMock
    ) -> None:
        """
        Test that retriable errors re-raise for Celery retry and do NOT record
        failure info on non-final attempts.
        """
        mock_export_direct.side_effect = CHQueryErrorTooManySimultaneousQueries("Too many queries")

        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
        )

        # Should raise - retriable errors are re-raised for Celery retry
        with pytest.raises(CHQueryErrorTooManySimultaneousQueries):
            exporter.export_asset(asset.id)

        asset.refresh_from_db()
        # On first attempt (retries=0), failure should NOT be recorded yet
        assert asset.exception is None
        assert asset.exception_type is None
        assert asset.failure_type is None

    @patch("posthog.tasks.exporter._is_final_export_attempt", return_value=True)
    @patch("posthog.tasks.exporter.export_asset_direct")
    def test_retriable_error_records_failure_on_final_attempt_regression(
        self, mock_export_direct: MagicMock, mock_is_final: MagicMock
    ) -> None:
        """
        Regression test for bug where retriable errors never recorded failure info.

        Previous buggy code:
            if is_retriable:
                raise  # <-- Would raise without recording failure!

            exported_asset.exception = str(e)
            exported_asset.exception_type = type(e).__name__
            exported_asset.save()

        This meant retriable errors that exhausted all retries would leave
        the ExportedAsset with no exception/exception_type/failure_type set.

        The fix ensures failure info is recorded on the final attempt before re-raising.
        """
        mock_export_direct.side_effect = CHQueryErrorTooManySimultaneousQueries("ClickHouse overloaded")

        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
        )

        with pytest.raises(CHQueryErrorTooManySimultaneousQueries):
            exporter.export_asset(asset.id)

        asset.refresh_from_db()
        # CRITICAL: These fields would have been None with the old buggy code
        assert asset.exception is not None, "Bug regression: exception not recorded for retriable error"
        assert asset.exception_type == "CHQueryErrorTooManySimultaneousQueries"
        assert asset.failure_type == "system"
