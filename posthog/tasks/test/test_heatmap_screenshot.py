from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.models.heatmap_saved import HeatmapSnapshot, SavedHeatmap
from posthog.tasks.heatmap_screenshot import generate_heatmap_screenshot


class TestHeatmapScreenshotTask(APIBaseTest):
    @patch("posthog.tasks.heatmap_screenshot.sync_playwright")
    def test_generates_multiple_width_snapshots_and_marks_completed(self, mock_sync_playwright: MagicMock) -> None:
        # Arrange Playwright mocks
        mock_p = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()

        # playwright context manager
        mock_sync_playwright.return_value.__enter__.return_value = mock_p
        mock_p.chromium.launch.return_value = mock_browser
        # context -> page
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        # mock page behavior
        mock_page.evaluate.return_value = 1200  # total page height
        # Return different bytes per screenshot call to verify width mapping
        mock_page.screenshot.side_effect = [b"jpeg320", b"jpeg768", b"jpeg1024"]

        heatmap = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            target_widths=[320, 768, 1024],
            status=SavedHeatmap.Status.PROCESSING,
        )

        # Act
        generate_heatmap_screenshot(heatmap.id)

        # Assert status and snapshots
        heatmap.refresh_from_db()
        assert heatmap.status == SavedHeatmap.Status.COMPLETED

        snaps = list(HeatmapSnapshot.objects.filter(heatmap=heatmap).order_by("width"))
        assert [s.width for s in snaps] == [320, 768, 1024]
        assert snaps[0].content == b"jpeg320"
        assert snaps[1].content == b"jpeg768"
        assert snaps[2].content == b"jpeg1024"

        # Ensure we cleaned up the browser
        mock_browser.close.assert_called_once()

    @patch("posthog.tasks.heatmap_screenshot.sync_playwright")
    def test_failure_marks_failed_and_records_exception(self, mock_sync_playwright: MagicMock) -> None:
        # Arrange: make playwright crash when entering context
        mock_sync_playwright.return_value.__enter__.side_effect = RuntimeError("boom")

        heatmap = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            target_widths=[320],
            status=SavedHeatmap.Status.PROCESSING,
        )

        # Act
        try:
            generate_heatmap_screenshot(heatmap.id)
        except RuntimeError:
            pass

        # Assert
        heatmap.refresh_from_db()
        assert heatmap.status == SavedHeatmap.Status.FAILED
        assert "boom" in (heatmap.exception or "")

    @patch("posthog.tasks.heatmap_screenshot.sync_playwright")
    def test_page_failure_captures_diagnostics_in_exception(self, mock_sync_playwright: MagicMock) -> None:
        # Arrange Playwright mocks that get through browser setup but fail on the screenshot call
        mock_p = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()

        mock_sync_playwright.return_value.__enter__.return_value = mock_p
        mock_p.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        # Make page look like a real page with a URL/title so diagnostics can be captured.
        mock_page.url = "https://example.com/failing-page"
        mock_page.title.return_value = "Broken Page"
        mock_page.evaluate.return_value = 1200

        # Fail during the screenshot step so we exercise the per-page except block.
        mock_page.screenshot.side_effect = RuntimeError("screenshot failed")

        heatmap = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com/failing-page",
            created_by=self.user,
            target_widths=[320],
            status=SavedHeatmap.Status.PROCESSING,
        )

        # Act
        try:
            generate_heatmap_screenshot(heatmap.id)
        except RuntimeError:
            pass

        # Assert: the saved exception should include the wrapped diagnostics.
        heatmap.refresh_from_db()
        assert heatmap.status == SavedHeatmap.Status.FAILED
        assert heatmap.exception is not None
        assert "RuntimeError" in heatmap.exception
        assert "screenshot failed" in heatmap.exception
        assert "url=https://example.com/failing-page" in heatmap.exception
        assert "title=Broken Page" in heatmap.exception
        # Context should be torn down even on failure
        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()
