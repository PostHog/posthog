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

    def test_create_upload_type_with_image_url(self):
        resp = self.client.post(
            f"/api/environments/{self.team.id}/saved/",
            {
                "type": "upload",
                "image_url": "/uploaded_media/550e8400-e29b-41d4-a716-446655440000",
                "data_url": "https://example.com/page/*",
            },
        )
        self.assertEqual(resp.status_code, 201)
        saved = SavedHeatmap.objects.get(id=resp.data["id"])
        self.assertEqual(saved.type, SavedHeatmap.Type.UPLOAD)
        self.assertEqual(saved.image_url, "/uploaded_media/550e8400-e29b-41d4-a716-446655440000")
        self.assertEqual(saved.status, SavedHeatmap.Status.COMPLETED)

    def test_upload_type_status_is_completed_immediately(self):
        resp = self.client.post(
            f"/api/environments/{self.team.id}/saved/",
            {
                "type": "upload",
                "image_url": "/uploaded_media/550e8400-e29b-41d4-a716-446655440000",
                "data_url": "https://example.com/*",
            },
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], "completed")

    def test_upload_type_url_is_optional(self):
        resp = self.client.post(
            f"/api/environments/{self.team.id}/saved/",
            {
                "type": "upload",
                "image_url": "/uploaded_media/550e8400-e29b-41d4-a716-446655440000",
                "data_url": "https://example.com/*",
            },
        )
        self.assertEqual(resp.status_code, 201)
        saved = SavedHeatmap.objects.get(id=resp.data["id"])
        self.assertEqual(saved.url, "")

    def test_upload_type_requires_image_url(self):
        resp = self.client.post(
            f"/api/environments/{self.team.id}/saved/",
            {
                "type": "upload",
                "data_url": "https://example.com/*",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("image_url", str(resp.data))

    def test_non_upload_type_requires_url(self):
        resp = self.client.post(
            f"/api/environments/{self.team.id}/saved/",
            {
                "type": "iframe",
                "data_url": "https://example.com/*",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("url", str(resp.data))

    def test_retrieve_upload_type_returns_image_url(self):
        saved = SavedHeatmap.objects.create(
            team=self.team,
            url="",
            data_url="https://example.com/*",
            type=SavedHeatmap.Type.UPLOAD,
            image_url="/uploaded_media/550e8400-e29b-41d4-a716-446655440000",
            status=SavedHeatmap.Status.COMPLETED,
            created_by=self.user,
        )
        resp = self.client.get(f"/api/environments/{self.team.id}/saved/{saved.short_id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["type"], "upload")
        self.assertEqual(resp.data["image_url"], "/uploaded_media/550e8400-e29b-41d4-a716-446655440000")

    def test_upload_type_rejects_invalid_image_url_format(self):
        # External URL should be rejected
        resp = self.client.post(
            f"/api/environments/{self.team.id}/saved/",
            {
                "type": "upload",
                "image_url": "https://evil.com/image.png",
                "data_url": "https://example.com/*",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("image_url", str(resp.data))

    def test_upload_type_rejects_arbitrary_path(self):
        # Arbitrary internal path should be rejected
        resp = self.client.post(
            f"/api/environments/{self.team.id}/saved/",
            {
                "type": "upload",
                "image_url": "/api/projects/1/some_secret",
                "data_url": "https://example.com/*",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("image_url", str(resp.data))

    def test_upload_type_accepts_absolute_url_from_uploaded_media(self):
        # Absolute URLs from uploaded_media API should be accepted
        resp = self.client.post(
            f"/api/environments/{self.team.id}/saved/",
            {
                "type": "upload",
                "image_url": "https://us.posthog.com/uploaded_media/550e8400-e29b-41d4-a716-446655440000",
                "data_url": "https://example.com/*",
            },
        )
        self.assertEqual(resp.status_code, 201)
        saved = SavedHeatmap.objects.get(id=resp.data["id"])
        self.assertEqual(saved.image_url, "https://us.posthog.com/uploaded_media/550e8400-e29b-41d4-a716-446655440000")
