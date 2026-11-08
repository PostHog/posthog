"""Documents attached to an account: quotes, order forms, contracts, and the organization's
legal documents. Nested under `/api/projects/:team_id/accounts/:account_id/documents/`."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from django.core.validators import URLValidator
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.http import content_disposition_header

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import PathParameter, TeamAndOrgViewSetMixin
from posthog.models.user import User

from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin
from products.customer_analytics.backend.facade import api, contracts
from products.customer_analytics.backend.facade.enums import (
    AccountDocumentSource,
    AccountDocumentStatus,
    AccountDocumentType,
)
from products.customer_analytics.backend.presentation.views.serializers import (
    AccountDocumentSerializer,
    AccountDocumentWriteSerializer,
    AccountLegalDocumentSerializer,
)

_PARENT_ACCOUNT_ID = PathParameter(type=UUID, description="UUID of the parent account.")

_LINK_URL_VALIDATOR = URLValidator(schemes=["http", "https"])


class PandaDocUnavailableError(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Couldn't reach PandaDoc. Try again in a moment."
    default_code = "pandadoc_unavailable"


def _resolve_reference(source: str, url: str) -> tuple[str, str]:
    """Split the request's `url` into the stored pair (external_url, pandadoc_document_id)."""
    if source == AccountDocumentSource.PANDADOC.value:
        pandadoc_document_id = api.parse_pandadoc_document_id(url)
        if pandadoc_document_id is None:
            raise ValidationError({"url": "Enter a PandaDoc document link or document id."})
        return "", pandadoc_document_id
    try:
        _LINK_URL_VALIDATOR(url)
    except Exception:
        raise ValidationError({"url": "Enter a valid http or https link."})
    return url, ""


def _safe_filename(title: str) -> str:
    cleaned = "".join(ch for ch in title if ch.isprintable() and ch not in '/\\"').strip()
    return f"{cleaned[:100] or 'document'}.pdf"


@extend_schema(tags=["customer_analytics"])
class AccountDocumentViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.GenericViewSet):
    scope_object = "account"
    scope_object_read_actions = ["list", "retrieve", "preview", "legal", "legal_download"]
    scope_object_write_actions = ["create", "partial_update", "destroy", "sync"]
    serializer_class = AccountDocumentSerializer
    path_parameters = {"account_id": _PARENT_ACCOUNT_ID}
    pagination_class = None

    def _account_id(self) -> str:
        """The parent account's id when the caller can see it; a 404 otherwise. Per-account write
        overrides are deliberately not enforced here, like the other account sub-resources."""
        account_id = api.get_accessible_account_id(
            self.team_id, self.parents_query_dict["account_id"], user_access_control=self.user_access_control
        )
        if account_id is None:
            raise NotFound()
        return account_id

    @extend_schema(responses={200: AccountDocumentSerializer(many=True)})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        documents = api.list_account_documents(self.team_id, self._account_id())
        return Response(AccountDocumentSerializer(documents, many=True).data)

    @extend_schema(responses={200: AccountDocumentSerializer})
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        document = api.get_account_document(self.team_id, self._account_id(), self.kwargs["pk"])
        if document is None:
            raise NotFound()
        return Response(AccountDocumentSerializer(document).data)

    @extend_schema(request=AccountDocumentWriteSerializer, responses={201: AccountDocumentSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        account_id = self._account_id()
        write = AccountDocumentWriteSerializer(data=request.data)
        write.is_valid(raise_exception=True)
        data = write.validated_data
        source = data.get("source", AccountDocumentSource.LINK.value)
        if "url" not in data:
            raise ValidationError({"url": "Enter a link to the document."})
        external_url, pandadoc_document_id = _resolve_reference(source, data["url"])
        title = data.get("title", "")
        if not title and source == AccountDocumentSource.LINK.value:
            raise ValidationError({"title": "Enter a title."})
        document = api.create_account_document(
            self.team_id,
            account_id,
            actor=cast(User, request.user),
            data=contracts.CreateAccountDocumentInput(
                title=title,
                document_type=data.get("document_type", AccountDocumentType.OTHER.value),
                status=data.get("status", AccountDocumentStatus.DRAFT.value),
                source=source,
                external_url=external_url,
                pandadoc_document_id=pandadoc_document_id,
                effective_date=data.get("effective_date"),
                end_date=data.get("end_date"),
                amount=data.get("amount"),
            ),
        )
        return Response(AccountDocumentSerializer(document).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=AccountDocumentWriteSerializer, responses={200: AccountDocumentSerializer})
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        account_id = self._account_id()
        current = api.get_account_document(self.team_id, account_id, self.kwargs["pk"])
        if current is None:
            raise NotFound()
        write = AccountDocumentWriteSerializer(data=request.data, partial=True)
        write.is_valid(raise_exception=True)
        data = write.validated_data

        source = data.get("source", current.source)
        reference: dict[str, Any] = {}
        if "url" in data or ("source" in data and source != current.source):
            if "url" not in data:
                raise ValidationError({"url": "Enter a link to the document for the new source."})
            external_url, pandadoc_document_id = _resolve_reference(source, data["url"])
            reference = {
                "external_url": external_url,
                "external_url_provided": True,
                "pandadoc_document_id": pandadoc_document_id,
                "pandadoc_document_id_provided": True,
            }
        if "title" in data and not data["title"] and source == AccountDocumentSource.LINK.value:
            raise ValidationError({"title": "Enter a title."})

        changes = contracts.UpdateAccountDocumentInput(
            title=data.get("title"),
            title_provided="title" in data,
            document_type=data.get("document_type"),
            document_type_provided="document_type" in data,
            status=data.get("status"),
            status_provided="status" in data,
            source=data.get("source"),
            source_provided="source" in data,
            effective_date=data.get("effective_date"),
            effective_date_provided="effective_date" in data,
            end_date=data.get("end_date"),
            end_date_provided="end_date" in data,
            amount=data.get("amount"),
            amount_provided="amount" in data,
            **reference,
        )
        document = api.update_account_document(self.team_id, account_id, self.kwargs["pk"], changes)
        if document is None:
            raise NotFound()
        return Response(AccountDocumentSerializer(document).data)

    @extend_schema(responses={204: None, 404: OpenApiResponse(description="No such document on this account.")})
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if not api.delete_account_document(self.team_id, self._account_id(), self.kwargs["pk"]):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        description="Re-read the document's name and status from PandaDoc and store them on the record.",
        request=None,
        responses={
            200: AccountDocumentSerializer,
            400: OpenApiResponse(description="The document is not linked to PandaDoc, or PandaDoc no longer has it."),
            404: OpenApiResponse(description="No such document on this account."),
            502: OpenApiResponse(description="PandaDoc could not be reached."),
        },
    )
    @action(methods=["POST"], detail=True)
    def sync(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        account_id = self._account_id()
        try:
            document = api.sync_account_document_from_pandadoc(self.team_id, account_id, self.kwargs["pk"])
        except api.PandaDocMissingId:
            raise ValidationError({"pandadoc_document_id": "This document isn't linked to PandaDoc."})
        except api.PandaDocDocumentMissing:
            raise ValidationError(
                {"pandadoc_document_id": "PandaDoc no longer has this document. Check the link in PandaDoc."}
            )
        except api.PandaDocUnavailable:
            raise PandaDocUnavailableError()
        if document is None:
            raise NotFound()
        return Response(AccountDocumentSerializer(document).data)

    @extend_schema(
        description="The document's current PDF rendition from PandaDoc, served inline so the account page can "
        "show an unsigned document in a frame. Available only for PandaDoc documents.",
        responses={
            (200, "application/pdf"): OpenApiTypes.BINARY,
            400: OpenApiResponse(description="The document is not linked to PandaDoc."),
            404: OpenApiResponse(description="No such document on this account, or PandaDoc no longer has it."),
            502: OpenApiResponse(description="PandaDoc could not be reached or has not rendered the PDF yet."),
        },
    )
    @action(methods=["GET"], detail=True)
    def preview(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        account_id = self._account_id()
        try:
            result = api.get_account_document_pdf(self.team_id, account_id, self.kwargs["pk"])
        except api.PandaDocMissingId:
            raise ValidationError({"pandadoc_document_id": "This document isn't linked to PandaDoc."})
        except api.PandaDocDocumentMissing:
            raise NotFound("PandaDoc no longer has this document.")
        except api.PandaDocUnavailable:
            raise PandaDocUnavailableError()
        if result is None:
            raise NotFound()
        title, content = result
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = (
            content_disposition_header(as_attachment=False, filename=_safe_filename(title)) or "inline"
        )
        # The rendition reflects whatever PandaDoc holds right now, so nothing may cache it.
        response["Cache-Control"] = "private, no-store"
        return response

    @extend_schema(
        description="The DPA, BAA and MSA the account's organization holds in PostHog. Empty when the account is "
        "not keyed on a PostHog organization id.",
        responses={200: AccountLegalDocumentSerializer(many=True)},
    )
    @action(methods=["GET"], detail=False)
    def legal(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        documents = api.list_account_legal_documents(self.team_id, self._account_id())
        return Response(AccountLegalDocumentSerializer(documents, many=True).data)

    @extend_schema(
        description="Redirects to a short-lived download URL for a signed legal document's PDF.",
        parameters=[
            OpenApiParameter(
                name="legal_document_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description="UUID of the legal document, from the legal documents list.",
            )
        ],
        responses={
            302: OpenApiResponse(description="Redirect to the download URL."),
            404: OpenApiResponse(description="No signed PDF is available for this legal document."),
        },
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path=r"legal/(?P<legal_document_id>[0-9a-fA-F-]{36})/download",
        url_name="legal-download",
    )
    def legal_download(self, request: Request, legal_document_id: str, *args: Any, **kwargs: Any) -> HttpResponse:
        url = api.get_account_legal_document_download_url(self.team_id, self._account_id(), UUID(legal_document_id))
        if url is None:
            raise NotFound()
        return HttpResponseRedirect(url)
