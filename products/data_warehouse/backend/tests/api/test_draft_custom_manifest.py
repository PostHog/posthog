from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache

import httpx
from openai import APIConnectionError
from parameterized import parameterized
from rest_framework import status

from posthog.models import Team

from products.warehouse_sources.backend.temporal.data_imports.sources.custom.ai_builder import ManifestDraftResult

_DRAFT_PATH = "products.data_warehouse.backend.presentation.views.external_data_source.draft_manifest_sync"
_FETCH_PATH = "products.data_warehouse.backend.presentation.views.external_data_source.fetch_docs_text"
_FLAG_PATH = "products.data_warehouse.backend.presentation.views.external_data_source.is_custom_source_ai_builder_enabled_for_team"
_THROTTLE_SCOPES = (
    "custom_source_ai_builder_burst",
    "custom_source_ai_builder_sustained",
    "custom_source_ai_builder_daily",
)


class TestDraftCustomManifest(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The AI builder is flag-gated; default it on so the other tests reach the logic under test.
        flag_patcher = patch(_FLAG_PATH, return_value=True)
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)

    def _url(self, team_id: int | None = None) -> str:
        return f"/api/environments/{team_id or self.team.pk}/external_data_sources/draft_custom_manifest/"

    def _approve_ai(self) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    def _reset_throttles(self, team_id: int | None = None) -> None:
        for scope in _THROTTLE_SCOPES:
            cache.delete(f"throttle_{scope}_{team_id or self.team.pk}")

    def test_blocks_when_feature_flag_disabled(self) -> None:
        self._approve_ai()
        with patch(_FLAG_PATH, return_value=False), patch(_FETCH_PATH) as fetch, patch(_DRAFT_PATH) as draft:
            response = self.client.post(self._url(), {"docs_url": "https://docs.example.com"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        fetch.assert_not_called()
        draft.assert_not_called()

    def test_blocks_when_ai_data_processing_not_approved(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        with patch(_FETCH_PATH) as fetch, patch(_DRAFT_PATH) as draft:
            response = self.client.post(self._url(), {"docs_url": "https://docs.example.com"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        fetch.assert_not_called()
        draft.assert_not_called()

    def test_requires_docs_url_or_text(self) -> None:
        self._approve_ai()
        response = self.client.post(self._url(), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_drafts_manifest_and_fetches_docs_server_side(self) -> None:
        self._approve_ai()
        result = ManifestDraftResult(
            status="ok", manifest_json='{"client": {}}', resource_names=["users"], attempts=2, error=None
        )
        with patch(_FETCH_PATH, return_value="DOCS") as fetch, patch(_DRAFT_PATH, return_value=result) as draft:
            response = self.client.post(self._url(), {"docs_url": "https://docs.example.com"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["draft_status"], "ok")
        self.assertEqual(data["resource_names"], ["users"])
        self.assertEqual(data["attempts"], 2)
        fetch.assert_called_once()
        # The URL is fetched server-side and the extracted text — not the raw URL — reaches the engine.
        self.assertEqual(draft.call_args.kwargs["docs_text"], "DOCS")

    @parameterized.expand(
        [
            ("gateway_unreachable", APIConnectionError(request=httpx.Request("POST", "https://gateway")), 503),
            ("gateway_failed", RuntimeError("boom"), 502),
        ]
    )
    def test_gateway_failure_errors_instead_of_returning_a_stub(
        self, _name: str, exc: Exception, expected: int
    ) -> None:
        self._approve_ai()
        with patch(_FETCH_PATH, return_value="DOCS"), patch(_DRAFT_PATH, side_effect=exc):
            response = self.client.post(self._url(), {"docs_url": "https://docs.example.com"})
        self.assertEqual(response.status_code, expected)
        # A failure must surface as an error, never as a canned 200 manifest.
        self.assertNotIn("manifest_json", response.json())

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_throttled_per_team_after_burst_limit(self, _enabled) -> None:
        self._approve_ai()
        self._reset_throttles()
        other = Team.objects.create(organization=self.organization, name="Other")
        self._reset_throttles(team_id=other.pk)

        result = ManifestDraftResult(status="ok", manifest_json="{}", resource_names=[], attempts=1, error=None)
        with patch(_FETCH_PATH, return_value="DOCS"), patch(_DRAFT_PATH, return_value=result):
            # Burst budget is 5/minute per team — the 6th request is rejected.
            for _ in range(5):
                ok = self.client.post(self._url(), {"docs_url": "https://docs.example.com"})
                self.assertEqual(ok.status_code, status.HTTP_200_OK)
            throttled = self.client.post(self._url(), {"docs_url": "https://docs.example.com"})
            self.assertEqual(throttled.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            self.assertIn("Retry-After", throttled.headers)

            # A different team shares no budget — the cap is keyed per team, not global.
            other_team = self.client.post(self._url(team_id=other.pk), {"docs_url": "https://docs.example.com"})
            self.assertEqual(other_team.status_code, status.HTTP_200_OK)
