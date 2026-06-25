from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.warehouse_sources.backend.temporal.data_imports.sources.custom.ai_builder import ManifestDraftResult

_DRAFT_PATH = "products.data_warehouse.backend.api.external_data_source.draft_manifest_sync"
_FETCH_PATH = "products.data_warehouse.backend.api.external_data_source.fetch_docs_text"


class TestDraftCustomManifest(APIBaseTest):
    def _url(self) -> str:
        return f"/api/environments/{self.team.pk}/external_data_sources/draft_custom_manifest/"

    def _approve_ai(self) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

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
