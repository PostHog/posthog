from datetime import UTC, datetime
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models.team import Team

from products.customer_analytics.backend.logic.account_documents import parse_pandadoc_document_id
from products.customer_analytics.backend.models import AccountDocument
from products.customer_analytics.backend.test.factories import create_account
from products.legal_documents.backend.facade import api as legal_documents_api
from products.legal_documents.backend.facade.contracts import LegalDocumentDTO, PandaDocDocumentDetails

PANDADOC_ID = "nPh2PDhFdDqAES9k64h9qX"
EDITOR_URL = f"https://app.pandadoc.com/a/#/documents/{PANDADOC_ID}"


class TestParsePandaDocDocumentId(SimpleTestCase):
    @parameterized.expand(
        [
            ("bare_id", PANDADOC_ID, PANDADOC_ID),
            ("editor_url", EDITOR_URL, PANDADOC_ID),
            ("editor_url_with_trailing_path", f"{EDITOR_URL}/recipients", PANDADOC_ID),
            ("direct_url", f"https://app.pandadoc.com/documents/{PANDADOC_ID}", PANDADOC_ID),
            ("query_url", f"https://app.pandadoc.com/document/v2?id={PANDADOC_ID}", PANDADOC_ID),
            ("padded_id", f"  {PANDADOC_ID} \n", PANDADOC_ID),
            ("signing_session_url", f"https://app.pandadoc.com/s/{PANDADOC_ID}", None),
            ("other_host", f"https://docs.example.com/documents/{PANDADOC_ID}", None),
            ("free_text", "the order form", None),
            ("empty", "", None),
        ]
    )
    def test_parse(self, _name: str, value: str, expected: str | None) -> None:
        assert parse_pandadoc_document_id(value) == expected


class TestAccountDocumentsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.account = create_account(team_id=self.team.id, name="Acme", external_id=str(self.organization.id))

    def _url(self, suffix: str = "", account_id: object | None = None) -> str:
        return f"/api/projects/{self.team.id}/accounts/{account_id or self.account.id}/documents/{suffix}"

    def _register_link(self, **overrides: object) -> dict:
        body = {"source": "link", "title": "Signed quote", "url": "https://docs.example.com/quote.pdf", **overrides}
        response = self.client.post(self._url(), body)
        assert response.status_code == status.HTTP_201_CREATED, response.content
        return response.json()

    def test_registering_a_pandadoc_document_reads_its_name_and_status(self) -> None:
        details = PandaDocDocumentDetails(
            id=PANDADOC_ID, name="Acme order form", status="document.sent", date_modified=None
        )
        with patch.object(legal_documents_api, "get_pandadoc_document_details", return_value=details) as get_details:
            response = self.client.post(
                self._url(), {"source": "pandadoc", "url": EDITOR_URL, "document_type": "order_form"}
            )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        get_details.assert_called_once_with(PANDADOC_ID)
        body = response.json()
        assert body["pandadoc_document_id"] == PANDADOC_ID
        assert body["external_url"] == ""
        assert body["title"] == "Acme order form"
        assert body["status"] == "sent"
        assert body["pandadoc_status"] == "document.sent"
        assert body["pandadoc_url"] == EDITOR_URL
        assert body["pandadoc_synced_at"] is not None

    def test_registering_a_pandadoc_document_survives_a_pandadoc_outage(self) -> None:
        with patch.object(
            legal_documents_api,
            "get_pandadoc_document_details",
            side_effect=legal_documents_api.PandaDocUnavailable("down"),
        ):
            response = self.client.post(self._url(), {"source": "pandadoc", "url": PANDADOC_ID, "title": "Order form"})

        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        assert body["title"] == "Order form"
        assert body["status"] == "draft"
        assert body["pandadoc_status"] == ""
        assert body["pandadoc_synced_at"] is None

    @parameterized.expand(
        [
            (
                "pandadoc_signing_link",
                {"source": "pandadoc", "url": f"https://app.pandadoc.com/s/{PANDADOC_ID}"},
                "url",
            ),
            ("link_without_title", {"source": "link", "url": "https://docs.example.com/quote.pdf"}, "title"),
            ("link_with_bad_url", {"source": "link", "title": "Quote", "url": "not a link"}, "url"),
            ("missing_url", {"source": "link", "title": "Quote"}, "url"),
        ]
    )
    def test_rejects_an_unusable_reference(self, _name: str, body: dict, field: str) -> None:
        response = self.client.post(self._url(), body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.json()["attr"] == field

    def test_lists_only_the_accounts_live_documents(self) -> None:
        kept = self._register_link(title="Kept")
        removed = self._register_link(title="Removed")
        other_account = create_account(team_id=self.team.id, name="Beta")
        AccountDocument.objects.for_team(self.team.id).create(
            team_id=self.team.id, account=other_account, title="Elsewhere", external_url="https://docs.example.com/x"
        )

        assert self.client.delete(self._url(f"{removed['id']}/")).status_code == status.HTTP_204_NO_CONTENT
        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        assert [document["id"] for document in response.json()] == [kept["id"]]
        assert AccountDocument.objects.for_team(self.team.id).get(id=removed["id"]).deleted_at is not None

    def test_another_teams_account_is_not_found(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        foreign_account = create_account(team_id=other_team.id, name="Foreign")

        response = self.client.get(self._url(account_id=foreign_account.id))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_updates_metadata_and_resolves_a_new_link(self) -> None:
        document = self._register_link()

        response = self.client.patch(
            self._url(f"{document['id']}/"),
            {
                "status": "signed",
                "effective_date": "2026-01-01",
                "end_date": None,
                "amount": "12000.50",
                "url": "https://docs.example.com/quote-v2.pdf",
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["status"] == "signed"
        assert body["effective_date"] == "2026-01-01"
        assert body["end_date"] is None
        assert body["amount"] == "12000.50"
        assert body["external_url"] == "https://docs.example.com/quote-v2.pdf"
        assert body["title"] == "Signed quote"

    @parameterized.expand(
        [
            ("pandadoc_down", legal_documents_api.PandaDocUnavailable("down"), status.HTTP_502_BAD_GATEWAY),
            ("deleted_in_pandadoc", None, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_sync_reports_a_pandadoc_failure(self, _name: str, outcome: Exception | None, expected_status: int) -> None:
        with patch.object(legal_documents_api, "get_pandadoc_document_details", return_value=None):
            document = self.client.post(
                self._url(), {"source": "pandadoc", "url": PANDADOC_ID, "title": "Quote"}
            ).json()

        with patch.object(legal_documents_api, "get_pandadoc_document_details", side_effect=outcome, return_value=None):
            response = self.client.post(self._url(f"{document['id']}/sync/"))

        assert response.status_code == expected_status, response.content

    def test_sync_refuses_a_linked_document(self) -> None:
        document = self._register_link()

        response = self.client.post(self._url(f"{document['id']}/sync/"))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "pandadoc_document_id"

    def test_preview_serves_the_pandadoc_pdf_inline(self) -> None:
        with patch.object(legal_documents_api, "get_pandadoc_document_details", return_value=None):
            document = self.client.post(
                self._url(), {"source": "pandadoc", "url": PANDADOC_ID, "title": 'Acme "Q4" quote'}
            ).json()

        with patch.object(legal_documents_api, "download_pandadoc_document_pdf", return_value=b"%PDF-1.4 example"):
            response = self.client.get(self._url(f"{document['id']}/preview/"))

        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "application/pdf"
        assert response["Content-Disposition"] == 'inline; filename="Acme Q4 quote.pdf"'
        assert response["Cache-Control"] == "private, no-store"
        assert response.content == b"%PDF-1.4 example"

    def test_legal_documents_come_from_the_accounts_organization(self) -> None:
        dto = LegalDocumentDTO(
            id=uuid4(),
            document_type="DPA",
            company_name="Acme Inc",
            representative_email="legal@example.com",
            status="signed",
            signed_pdf_stored=True,
            created_by=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        with patch.object(legal_documents_api, "list_for_organization", return_value=[dto]) as list_for_organization:
            response = self.client.get(self._url("legal/"))

        assert response.status_code == status.HTTP_200_OK, response.content
        list_for_organization.assert_called_once_with(self.organization.id)
        assert response.json() == [
            {
                "id": str(dto.id),
                "document_type": "DPA",
                "status": "signed",
                "company_name": "Acme Inc",
                "representative_email": "legal@example.com",
                "created_at": "2026-01-01T00:00:00Z",
                "download_available": True,
            }
        ]

    def test_an_account_keyed_on_a_group_key_has_no_legal_documents(self) -> None:
        group_keyed = create_account(team_id=self.team.id, name="Beta", external_id="beta-inc")

        with patch.object(legal_documents_api, "list_for_organization") as list_for_organization:
            response = self.client.get(self._url("legal/", account_id=group_keyed.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []
        list_for_organization.assert_not_called()

    @parameterized.expand(
        [
            ("signed", "https://storage.example.com/signed.pdf", status.HTTP_302_FOUND),
            ("not_signed_yet", None, status.HTTP_404_NOT_FOUND),
        ]
    )
    def test_legal_download_redirects_to_the_signed_pdf(
        self, _name: str, download_url: str | None, expected_status: int
    ) -> None:
        legal_document_id = uuid4()
        with patch.object(legal_documents_api, "get_signed_pdf_download_url", return_value=download_url) as get_url:
            response = self.client.get(self._url(f"legal/{legal_document_id}/download/"))

        assert response.status_code == expected_status
        get_url.assert_called_once_with(legal_document_id, self.organization.id)
        if download_url:
            assert response["Location"] == download_url
