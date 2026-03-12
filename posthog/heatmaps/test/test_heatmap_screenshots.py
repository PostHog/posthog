from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework.test import APIClient

from posthog.models import HeatmapSnapshot, SavedHeatmap, Team


class TestHeatmapsAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch("posthog.tasks.heatmap_screenshot.generate_heatmap_screenshot.delay")
    def test_generate_creates_saved_with_target_widths(self, mock_task):
        resp = self.client.post(
            f"/api/environments/{self.team.id}/saved/",
            {"url": "https://example.com", "widths": [768, 1024]},
        )
        self.assertEqual(resp.status_code, 201)
        saved = SavedHeatmap.objects.get(id=resp.data["id"])
        self.assertEqual(saved.url, "https://example.com")
        self.assertEqual(saved.created_by, self.user)
        self.assertEqual(saved.status, SavedHeatmap.Status.PROCESSING)
        self.assertEqual(saved.target_widths, [768, 1024])
        mock_task.assert_called_once_with(saved.id)

    def test_content_returns_202_until_snapshot_exists(self):
        saved = SavedHeatmap.objects.create(team=self.team, url="https://example.com", created_by=self.user)
        r = self.client.get(f"/api/environments/{self.team.id}/heatmap_screenshots/{saved.id}/content/?width=1024")
        self.assertEqual(r.status_code, 202)

    def test_content_returns_snapshot_bytes_and_defaults_width(self):
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            status=SavedHeatmap.Status.COMPLETED,
        )
        HeatmapSnapshot.objects.create(heatmap=saved, width=1024, content=b"jpegdata1024")
        r = self.client.get(f"/api/environments/{self.team.id}/heatmap_screenshots/{saved.id}/content/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        self.assertTrue(r["Content-Disposition"].endswith('1024.jpg"'))
        self.assertEqual(r.content, b"jpegdata1024")

    def test_content_picks_closest_snapshot_when_exact_missing(self):
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            status=SavedHeatmap.Status.COMPLETED,
        )
        HeatmapSnapshot.objects.create(heatmap=saved, width=768, content=b"jpeg768")
        HeatmapSnapshot.objects.create(heatmap=saved, width=1024, content=b"jpeg1024")
        # Request 800 should pick 768 (closest)
        r = self.client.get(f"/api/environments/{self.team.id}/heatmap_screenshots/{saved.id}/content/?width=800")
        self.assertEqual(r.status_code, 200)
        self.assertIn('768.jpg"', r["Content-Disposition"])
        self.assertEqual(r.content, b"jpeg768")

    def test_saved_list_excludes_deleted_and_includes_created_by(self):
        SavedHeatmap.objects.create(team=self.team, url="https://a.example", created_by=self.user)
        SavedHeatmap.objects.create(team=self.team, url="https://b.example", created_by=self.user, deleted=True)
        r = self.client.get(f"/api/environments/{self.team.id}/saved/")
        self.assertEqual(r.status_code, 200)
        urls = [x["url"] for x in r.data["results"]]
        self.assertIn("https://a.example", urls)
        self.assertNotIn("https://b.example", urls)
        # created_by present
        found = next(x for x in r.data["results"] if x["url"] == "https://a.example")
        self.assertEqual(found["created_by"]["id"], self.user.id)

    def test_team_isolation_for_content(self):
        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other Team"
        )
        other = SavedHeatmap.objects.create(team=other_team, url="https://example.com")
        r = self.client.get(f"/api/environments/{self.team.id}/heatmap_screenshots/{other.id}/content/")
        self.assertEqual(r.status_code, 404)

    @patch("posthog.heatmaps.heatmaps_api.generate_heatmap_screenshot")
    def test_retrieve_auto_recovers_stale_processing_heatmap(self, mock_task):
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            status=SavedHeatmap.Status.PROCESSING,
            type=SavedHeatmap.Type.SCREENSHOT,
        )
        HeatmapSnapshot.objects.create(heatmap=saved, width=1024, content=b"old")

        # Force updated_at to 15 minutes ago
        SavedHeatmap.objects.filter(id=saved.id).update(updated_at=timezone.now() - timedelta(minutes=15))

        r = self.client.get(f"/api/environments/{self.team.id}/saved/{saved.short_id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "processing")

        # Task was re-enqueued
        mock_task.delay.assert_called_once_with(saved.id)

        # Old snapshots were cleaned up
        self.assertEqual(HeatmapSnapshot.objects.filter(heatmap=saved).count(), 0)

    @patch("posthog.heatmaps.heatmaps_api.generate_heatmap_screenshot")
    def test_retrieve_does_not_recover_recent_processing_heatmap(self, mock_task):
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            status=SavedHeatmap.Status.PROCESSING,
            type=SavedHeatmap.Type.SCREENSHOT,
        )

        r = self.client.get(f"/api/environments/{self.team.id}/saved/{saved.short_id}/")
        self.assertEqual(r.status_code, 200)

        # Task was NOT re-enqueued (still within threshold)
        mock_task.delay.assert_not_called()

    @patch("posthog.heatmaps.heatmaps_api.generate_heatmap_screenshot")
    def test_regenerate_endpoint_re_enqueues_task(self, mock_task):
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            status=SavedHeatmap.Status.FAILED,
            type=SavedHeatmap.Type.SCREENSHOT,
            exception="previous error",
        )
        HeatmapSnapshot.objects.create(heatmap=saved, width=1024, content=b"old")

        r = self.client.post(f"/api/environments/{self.team.id}/saved/{saved.short_id}/regenerate/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "processing")
        self.assertIsNone(r.data["exception"])

        mock_task.delay.assert_called_once_with(saved.id)
        self.assertEqual(HeatmapSnapshot.objects.filter(heatmap=saved).count(), 0)

    def test_regenerate_rejects_non_screenshot_type(self):
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="https://example.com",
            created_by=self.user,
            type=SavedHeatmap.Type.IFRAME,
        )

        r = self.client.post(f"/api/environments/{self.team.id}/saved/{saved.short_id}/regenerate/")
        self.assertEqual(r.status_code, 400)
