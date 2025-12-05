from posthog.test.base import APIBaseTest
from unittest.mock import patch

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
