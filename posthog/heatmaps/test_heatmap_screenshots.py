from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import TestCase

from rest_framework.test import APIClient

from posthog.models.heatmap_screenshot import HeatmapScreenshot


class TestHeatmapScreenshots(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch("posthog.tasks.heatmap_screenshot.generate_heatmap_screenshot.delay")
    def test_generate_screenshot_new(self, mock_task):
        """Test generating a new screenshot"""
        response = self.client.post(
            f"/api/environments/{self.team.id}/heatmap_screenshots/generate/",
            {"url": "https://example.com", "width": 1200},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["url"], "https://example.com")
        self.assertEqual(response.data["width"], 1200)
        self.assertEqual(response.data["status"], "processing")

        # Check database
        screenshot = HeatmapScreenshot.objects.get(id=response.data["id"])
        self.assertEqual(screenshot.team, self.team)
        self.assertEqual(screenshot.url, "https://example.com")
        self.assertEqual(screenshot.width, 1200)
        self.assertEqual(screenshot.created_by, self.user)

        # Check task was called
        mock_task.assert_called_once_with(screenshot.id)

    def test_generate_screenshot_existing_completed(self):
        """Test returning existing completed screenshot"""
        # Create existing completed screenshot
        existing = HeatmapScreenshot.objects.create(
            team=self.team,
            url="https://example.com",
            width=1400,
            status=HeatmapScreenshot.Status.COMPLETED,
            content=b"fake_image_data",
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/heatmap_screenshots/generate/", {"url": "https://example.com"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(existing.id))
        self.assertEqual(response.data["status"], "completed")

    def test_generate_screenshot_existing_processing(self):
        """Test returning existing processing screenshot"""
        # Create existing processing screenshot
        existing = HeatmapScreenshot.objects.create(
            team=self.team, url="https://example.com", width=1400, status=HeatmapScreenshot.Status.PROCESSING
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/heatmap_screenshots/generate/", {"url": "https://example.com"}
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["id"], str(existing.id))
        self.assertEqual(response.data["status"], "processing")

    @patch("posthog.tasks.heatmap_screenshot.generate_heatmap_screenshot.delay")
    def test_force_reload(self, mock_task):
        """Test force reloading existing screenshot"""
        # Create existing completed screenshot
        existing = HeatmapScreenshot.objects.create(
            team=self.team,
            url="https://example.com",
            width=1400,
            status=HeatmapScreenshot.Status.COMPLETED,
            content=b"fake_image_data",
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/heatmap_screenshots/generate/",
            {"url": "https://example.com", "force_reload": True},
        )

        self.assertEqual(response.status_code, 202)
        existing.refresh_from_db()
        self.assertEqual(existing.status, HeatmapScreenshot.Status.PROCESSING)
        self.assertIsNone(existing.content)
        self.assertEqual(existing.created_by, self.user)

        # Check task was called
        mock_task.assert_called_once_with(existing.id)

    def test_generate_screenshot_validation_errors(self):
        """Test validation errors for invalid input"""
        # Missing URL
        response = self.client.post(f"/api/environments/{self.team.id}/heatmap_screenshots/generate/", {"width": 1200})
        self.assertEqual(response.status_code, 400)
        self.assertIn("url", str(response.data))

        # Invalid width
        response = self.client.post(
            f"/api/environments/{self.team.id}/heatmap_screenshots/generate/",
            {"url": "https://example.com", "width": 50},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("width", str(response.data))

    def test_content_endpoint_no_content(self):
        """Test content endpoint when screenshot has no content"""
        screenshot = HeatmapScreenshot.objects.create(
            team=self.team, url="https://example.com", width=1400, status=HeatmapScreenshot.Status.PROCESSING
        )

        response = self.client.get(f"/api/environments/{self.team.id}/heatmap_screenshots/{screenshot.id}/content/")

        self.assertEqual(response.status_code, 404)

    def test_content_endpoint_with_content(self):
        """Test content endpoint when screenshot has content"""
        fake_image_data = b"fake_png_data"
        screenshot = HeatmapScreenshot.objects.create(
            team=self.team,
            url="https://example.com",
            width=1400,
            status=HeatmapScreenshot.Status.COMPLETED,
            content=fake_image_data,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/heatmap_screenshots/{screenshot.id}/content/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, fake_image_data)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("attachment", response["Content-Disposition"])

    def test_team_isolation(self):
        """Test that screenshots are isolated by team"""
        from posthog.models import Team

        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other Team"
        )

        # Create screenshot for other team
        other_screenshot = HeatmapScreenshot.objects.create(
            team=other_team,
            url="https://example.com",
            width=1400,
            status=HeatmapScreenshot.Status.COMPLETED,
            content=b"fake_image_data",
        )

        # Try to access from current team - should fail
        response = self.client.get(
            f"/api/environments/{self.team.id}/heatmap_screenshots/{other_screenshot.id}/content/"
        )

        self.assertEqual(response.status_code, 404)

    def test_default_width(self):
        """Test that default width is applied when not specified"""
        with patch("posthog.tasks.heatmap_screenshot.generate_heatmap_screenshot.delay"):
            response = self.client.post(
                f"/api/environments/{self.team.id}/heatmap_screenshots/generate/", {"url": "https://example.com"}
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["width"], 1400)  # Default width

    def test_unique_constraint(self):
        """Test that unique constraint works for team, url, width"""
        # Create first screenshot with content
        HeatmapScreenshot.objects.create(
            team=self.team,
            url="https://example.com",
            width=1400,
            status=HeatmapScreenshot.Status.COMPLETED,
            content=b"fake_image_data",  # Add content so it's considered complete
        )

        # Try to create duplicate - should reuse existing
        with patch("posthog.tasks.heatmap_screenshot.generate_heatmap_screenshot.delay"):
            response = self.client.post(
                f"/api/environments/{self.team.id}/heatmap_screenshots/generate/",
                {"url": "https://example.com", "width": 1400},
            )

        self.assertEqual(response.status_code, 200)  # Returns existing
        self.assertEqual(HeatmapScreenshot.objects.filter(team=self.team).count(), 1)


class TestHeatmapScreenshotModel(TestCase):
    def test_has_content_property(self):
        """Test the has_content property"""
        screenshot = HeatmapScreenshot(content=None, content_location=None)
        self.assertFalse(screenshot.has_content)

        screenshot.content = b"fake_data"
        self.assertTrue(screenshot.has_content)

        screenshot.content = None
        screenshot.content_location = "s3://bucket/key"
        self.assertTrue(screenshot.has_content)

    def test_get_analytics_metadata(self):
        """Test analytics metadata generation"""
        screenshot = HeatmapScreenshot(
            team_id=123, url="https://example.com", width=1400, status=HeatmapScreenshot.Status.COMPLETED
        )

        metadata = screenshot.get_analytics_metadata()
        expected = {"team_id": 123, "url": "https://example.com", "width": 1400, "status": "completed"}
        self.assertEqual(metadata, expected)
