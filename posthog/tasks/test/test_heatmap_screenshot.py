from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from celery.exceptions import SoftTimeLimitExceeded

from posthog.models.heatmap_saved import HeatmapSnapshot, SavedHeatmap
from posthog.tasks.heatmap_screenshot import (
    SCREENSHOT_HARD_TIME_LIMIT,
    SCREENSHOT_SOFT_TIME_LIMIT,
    generate_heatmap_screenshot,
)


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
    def test_soft_time_limit_marks_failed_and_does_not_retry(self, mock_sync_playwright: MagicMock) -> None:
        mock_sync_playwright.return_value.__enter__.side_effect = SoftTimeLimitExceeded()

        heatmap = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            target_widths=[320],
            status=SavedHeatmap.Status.PROCESSING,
        )

        # Should swallow the SoftTimeLimitExceeded so Celery does not autoretry
        # and burn the same budget on a wedged page.
        result = generate_heatmap_screenshot(heatmap.id)
        assert result is None

        heatmap.refresh_from_db()
        assert heatmap.status == SavedHeatmap.Status.FAILED
        assert "timed out" in (heatmap.exception or "").lower()
        assert str(SCREENSHOT_SOFT_TIME_LIMIT) in (heatmap.exception or "")

    def test_task_has_time_limits_configured(self) -> None:
        # Guards against accidentally removing the time limits, which is the only
        # thing keeping a wedged Playwright run from holding a row in PROCESSING
        # forever.
        assert generate_heatmap_screenshot.soft_time_limit == SCREENSHOT_SOFT_TIME_LIMIT
        assert generate_heatmap_screenshot.time_limit == SCREENSHOT_HARD_TIME_LIMIT
        assert SCREENSHOT_SOFT_TIME_LIMIT < SCREENSHOT_HARD_TIME_LIMIT
