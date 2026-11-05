"""Account documents: quotes, order forms, contracts and legal documents attached to an account.

Two kinds of document meet here. Documents a person registers on the account (`AccountDocument`)
hold metadata plus a reference, either a PandaDoc document id or a plain link. Legal documents the
customer signed self-serve (DPA, BAA, MSA) live in the legal_documents product, keyed by the
organization behind the account's `external_id`, and are read through that product's facade.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from django.db.models import QuerySet
from django.utils import timezone

import structlog

from posthog.models.user import User

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.facade.enums import AccountDocumentSource, AccountDocumentStatus
from products.customer_analytics.backend.models import Account, AccountDocument
from products.legal_documents.backend.facade import api as legal_documents_api
from products.legal_documents.backend.facade.enums import LegalDocumentStatus

logger = structlog.get_logger(__name__)

PANDADOC_APP_ORIGIN = "https://app.pandadoc.com"

# PandaDoc document ids are opaque alphanumeric strings. The length bound keeps a short path
# segment such as a locale from being read as a document id.
_PANDADOC_DOCUMENT_ID = re.compile(r"^[A-Za-z0-9]{8,64}$")
_PANDADOC_DOCUMENT_PATH = re.compile(r"documents?/([A-Za-z0-9]{8,64})(?:[/?#]|$)")

# The PDF rendition is read into memory before it is served, so a runaway document cannot
# exhaust a worker.
PANDADOC_PDF_MAX_BYTES = 25 * 1024 * 1024

# PandaDoc's lifecycle statuses, normalized to the states the account page reasons about.
# A status missing here leaves the normalized status untouched.
# https://developers.pandadoc.com/reference/document-status
PANDADOC_STATUS_TO_DOCUMENT_STATUS: dict[str, AccountDocumentStatus] = {
    "document.uploaded": AccountDocumentStatus.DRAFT,
    "document.draft": AccountDocumentStatus.DRAFT,
    "document.scheduled": AccountDocumentStatus.DRAFT,
    "document.error": AccountDocumentStatus.DRAFT,
    "document.external_review": AccountDocumentStatus.DRAFT,
    "document.rejected": AccountDocumentStatus.DRAFT,
    "document.sent": AccountDocumentStatus.SENT,
    "document.viewed": AccountDocumentStatus.SENT,
    "document.waiting_approval": AccountDocumentStatus.SENT,
    "document.approved": AccountDocumentStatus.SENT,
    "document.waiting_pay": AccountDocumentStatus.SENT,
    "document.paid": AccountDocumentStatus.SIGNED,
    "document.completed": AccountDocumentStatus.SIGNED,
    "document.voided": AccountDocumentStatus.VOIDED,
    "document.declined": AccountDocumentStatus.VOIDED,
}


class PandaDocMissingId(Exception):
    """The document is not linked to PandaDoc, so there is nothing to read."""


class PandaDocDocumentMissing(Exception):
    """PandaDoc has no document with the stored id: it was deleted there, or the id was never valid."""


class PandaDocUnavailable(Exception):
    """PandaDoc could not answer: the API key is missing, the request failed, or the PDF is not ready."""


def parse_pandadoc_document_id(value: str) -> str | None:
    """The PandaDoc document id in a bare id or an app.pandadoc.com document URL, else ``None``.

    Accepts the editor URL (`/a/#/documents/<id>`), the direct document URL (`/documents/<id>`),
    and the `?id=<id>` form. A signing-session URL (`/s/<session>`) carries no document id and is
    rejected, because a session id cannot be read back through the documents API.
    """
    candidate = value.strip()
    if _PANDADOC_DOCUMENT_ID.match(candidate):
        return candidate
    parsed = urlsplit(candidate)
    if parsed.scheme not in ("http", "https"):
        return None
    host = parsed.hostname or ""
    if host != "pandadoc.com" and not host.endswith(".pandadoc.com"):
        return None
    for segment in (parsed.fragment, parsed.path):
        match = _PANDADOC_DOCUMENT_PATH.search(segment)
        if match:
            return match.group(1)
    query_ids = parse_qs(parsed.query).get("id") or parse_qs(urlsplit(parsed.fragment).query).get("id")
    if query_ids and _PANDADOC_DOCUMENT_ID.match(query_ids[0]):
        return query_ids[0]
    return None


def pandadoc_document_url(pandadoc_document_id: str) -> str:
    return f"{PANDADOC_APP_ORIGIN}/a/#/documents/{pandadoc_document_id}"


def normalize_pandadoc_status(pandadoc_status: str) -> AccountDocumentStatus | None:
    return PANDADOC_STATUS_TO_DOCUMENT_STATUS.get(pandadoc_status)


def list_account_documents(team_id: int, account_id: str | UUID) -> QuerySet[AccountDocument]:
    return (
        AccountDocument.objects.for_team(team_id)
        .filter(account_id=account_id, deleted_at__isnull=True)
        .order_by("-created_at")
    )


def get_account_document(team_id: int, account_id: str | UUID, document_id: str | UUID) -> AccountDocument | None:
    try:
        return list_account_documents(team_id, account_id).get(id=document_id)
    except (AccountDocument.DoesNotExist, ValueError):
        return None


def create_account_document(
    *, team_id: int, account_id: str | UUID, actor: User | None, data: contracts.CreateAccountDocumentInput
) -> AccountDocument:
    document = AccountDocument.objects.for_team(team_id).create(
        team_id=team_id,
        account_id=account_id,
        created_by=actor,
        title=data.title,
        document_type=data.document_type,
        status=data.status,
        source=data.source,
        external_url=data.external_url,
        pandadoc_document_id=data.pandadoc_document_id,
        effective_date=data.effective_date,
        end_date=data.end_date,
        amount=data.amount,
    )
    if document.source == AccountDocumentSource.PANDADOC.value:
        # Registration must not depend on PandaDoc being up: a row with no status yet is more
        # useful than a failed save, and the sync action reads PandaDoc again later.
        try:
            sync_account_document_from_pandadoc(document)
        except (PandaDocMissingId, PandaDocDocumentMissing, PandaDocUnavailable) as exc:
            logger.info("account_document_initial_pandadoc_sync_skipped", document_id=str(document.id), reason=str(exc))
    return document


def update_account_document(
    document: AccountDocument, changes: contracts.UpdateAccountDocumentInput
) -> AccountDocument:
    update_fields: list[str] = ["updated_at"]
    for field in (
        "title",
        "document_type",
        "status",
        "source",
        "external_url",
        "pandadoc_document_id",
        "effective_date",
        "end_date",
        "amount",
    ):
        if getattr(changes, f"{field}_provided"):
            setattr(document, field, getattr(changes, field))
            update_fields.append(field)
    if changes.pandadoc_document_id_provided:
        # A different PandaDoc document means the cached status describes the old one.
        document.pandadoc_status = ""
        document.pandadoc_synced_at = None
        update_fields.extend(["pandadoc_status", "pandadoc_synced_at"])
    document.save(update_fields=update_fields)
    return document


def delete_account_document(document: AccountDocument) -> None:
    document.deleted_at = timezone.now()
    document.save(update_fields=["deleted_at", "updated_at"])


def sync_account_document_from_pandadoc(document: AccountDocument) -> AccountDocument:
    """Read the document's current name and status from PandaDoc and store them on the row.

    The normalized `status` follows PandaDoc only when PandaDoc reports a status this module
    knows, so a status set by hand survives an unknown PandaDoc state. The title is filled from
    PandaDoc only while it is empty, because the person who registered the document chose it.
    """
    if not document.pandadoc_document_id:
        raise PandaDocMissingId("Document is not linked to a PandaDoc document.")
    try:
        details = legal_documents_api.get_pandadoc_document_details(document.pandadoc_document_id)
    except legal_documents_api.PandaDocUnavailable as exc:
        raise PandaDocUnavailable(str(exc)) from exc
    if details is None:
        raise PandaDocDocumentMissing(f"PandaDoc has no document {document.pandadoc_document_id}.")

    update_fields = ["pandadoc_status", "pandadoc_synced_at", "updated_at"]
    document.pandadoc_status = details.status
    document.pandadoc_synced_at = timezone.now()
    normalized = normalize_pandadoc_status(details.status)
    if normalized is not None and normalized.value != document.status:
        document.status = normalized.value
        update_fields.append("status")
    if not document.title and details.name:
        document.title = details.name[:512]
        update_fields.append("title")
    document.save(update_fields=update_fields)
    return document


def get_account_document_pdf(document: AccountDocument) -> bytes:
    """The current PDF rendition of the linked PandaDoc document, signed or not.

    PandaDoc renders drafts and sent documents on request, which is what lets the account page
    show an unsigned order form without copying a file into PostHog.
    """
    if not document.pandadoc_document_id:
        raise PandaDocMissingId("Document is not linked to a PandaDoc document.")
    try:
        content = legal_documents_api.download_pandadoc_document_pdf(
            document.pandadoc_document_id, max_bytes=PANDADOC_PDF_MAX_BYTES
        )
    except legal_documents_api.PandaDocUnavailable as exc:
        raise PandaDocUnavailable(str(exc)) from exc
    if content is None:
        raise PandaDocDocumentMissing(f"PandaDoc has no document {document.pandadoc_document_id}.")
    return content


def get_account(team_id: int, account_id: str | UUID) -> Account | None:
    try:
        return Account.objects.for_team(team_id).get(id=account_id)
    except (Account.DoesNotExist, ValueError):
        return None


def organization_id_for_account(account: Account) -> UUID | None:
    """The PostHog organization an account stands for, when its external id is one.

    Customer analytics does not require `external_id` to be an organization id; a team may key
    accounts on any group key. Only organization-keyed accounts can have legal documents.
    """
    if not account.external_id:
        return None
    try:
        return UUID(account.external_id)
    except ValueError:
        return None


def list_account_legal_documents(account: Account) -> list[contracts.AccountLegalDocumentView]:
    organization_id = organization_id_for_account(account)
    if organization_id is None:
        return []
    return [
        contracts.AccountLegalDocumentView(
            id=document.id,
            document_type=document.document_type,
            status=document.status,
            company_name=document.company_name,
            representative_email=document.representative_email,
            created_at=document.created_at,
            download_available=document.status == LegalDocumentStatus.SIGNED and document.signed_pdf_stored,
        )
        for document in legal_documents_api.list_for_organization(organization_id)
    ]


def get_account_legal_document_download_url(account: Account, legal_document_id: UUID) -> str | None:
    organization_id = organization_id_for_account(account)
    if organization_id is None:
        return None
    return legal_documents_api.get_signed_pdf_download_url(legal_document_id, organization_id)
