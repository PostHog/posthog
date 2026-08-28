"""DRF views for the customer_analytics account CRUD endpoints.

Thin HTTP layer: these viewsets validate requests, gate access through the standard
mixins, and shape responses, but reach all product data through the facade — no product
models are imported here. Request validation, status codes, ``@extend_schema`` parameter
declarations, pagination wiring, and the markdown→tiptap normalization for account
notebooks stay here; team/object access filtering, transactions, conflict handling,
pydantic-error formatting, and activity logging live behind the facade.
"""

# Lazy annotations: each ViewSet defines a ``list`` method, which would otherwise shadow the
# ``list`` builtin for any ``list[...]`` annotation evaluated later in the same class body.
from __future__ import annotations

import json
import builtins
from dataclasses import asdict
from typing import Any, cast
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import DomainNameValidator
from django.db import transaction
from django.http import HttpResponse

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.tagged_item import TaggedItemViewSetMixin
from posthog.cdp.services.icons import CDPIconsService
from posthog.event_usage import report_user_action
from posthog.exceptions import Conflict
from posthog.helpers.impersonation import is_impersonated
from posthog.models import OrganizationMembership
from posthog.models.user import User
from posthog.permissions import (
    PostHogFeatureFlagPermission,
    TeamMemberLightManagementPermission,
    TeamMemberStrictManagementPermission,
    get_authenticator_scopes,
    is_service_auth,
)
from posthog.rate_limit import RunSavedQueryRateThrottle

from products.access_control.backend.facade.user_access_control import UserAccessControl, model_to_resource
from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin
from products.customer_analytics.backend.facade import api, contracts
from products.customer_analytics.backend.facade.constants import (
    CUSTOMER_ANALYTICS_FEATURE_REQUESTS_FLAG,
    CUSTOMER_ANALYTICS_TRACK_RULES_FLAG,
)
from products.customer_analytics.backend.presentation.views.serializers import (
    AccountChannelSummarySerializer,
    AccountEmailThreadMessageSerializer,
    AccountEmailThreadSerializer,
    AccountNotebookSerializer,
    AccountNoteSerializer,
    AccountRelationshipDefinitionSerializer,
    AccountRelationshipSerializer,
    AccountRelationshipWriteSerializer,
    AccountSerializer,
    AccountTrackRulePreviewSerializer,
    AccountTrackRuleRunRequestSerializer,
    AccountTrackRuleRunSerializer,
    AccountTrackRulesConfigSerializer,
    CalendarSyncStatusSerializer,
    CalendarSyncTriggerResponseSerializer,
    CalendarSyncTriggerSerializer,
    CustomerJourneySerializer,
    CustomerProfileConfigSerializer,
    CustomPropertyDefinitionSerializer,
    CustomPropertySourceSerializer,
    CustomPropertySourceUpdateSerializer,
    CustomPropertySyncRunListQuerySerializer,
    CustomPropertySyncRunSerializer,
    CustomPropertySyncTriggerResponseSerializer,
    CustomPropertyValueSerializer,
    CustomPropertyValueSuggestionsResponseSerializer,
    CustomPropertyValueWriteSerializer,
    EventStreamMemberWriteSerializer,
    EventStreamSerializer,
    EventStreamTestMessageSerializer,
    FeatureRequestAddAccountSerializer,
    FeatureRequestCreateSerializer,
    FeatureRequestEvidenceCreateSerializer,
    FeatureRequestEvidenceDeleteSerializer,
    FeatureRequestEvidenceUpdateSerializer,
    FeatureRequestHistorySerializer,
    FeatureRequestListQuerySerializer,
    FeatureRequestProductAreaListQuerySerializer,
    FeatureRequestProductAreaSerializer,
    FeatureRequestSerializer,
    FeatureRequestStatusHistorySerializer,
    FeatureRequestUpdateSerializer,
    FeatureRequestVersionSerializer,
    MeetingSerializer,
    SupportTicketMessageSerializer,
    SupportTicketSerializer,
)

from ee.hogai.tools.create_notebook.tiptap import markdown_to_tiptap_nodes

# Object-level access levels for the resource ViewSets, matching what
# ``AccessControlPermission._get_required_access_level`` derives for these scope objects:
# reads need "viewer", writes need "editor".
_OBJECT_READ_LEVEL = "viewer"
_OBJECT_WRITE_LEVEL = "editor"

_ICON_DOMAIN_VALIDATOR = DomainNameValidator(accept_idna=False)


# The warehouse resources a person/group-property source can bind to: the import source behind a
# table, or a materialized view. Each needs its own API-token scope folded into the object check.
_WAREHOUSE_SCOPE_GATED_RESOURCES = frozenset({"external_data_source", "warehouse_view"})


class _WarehouseScopeGatedAccessControl:
    """Wraps ``UserAccessControl`` so object-level warehouse access additionally requires the request
    token to carry the matching scope for that resource (``read`` for viewer, ``write`` for editor) —
    ``external_data_source`` for a table binding, ``warehouse_view`` for a view binding.
    Person-property sources gate all warehouse read/write through ``check_access_level_for_object`` on
    the bound warehouse object, so folding the token scope in here enforces the cross-resource scope on
    every path without threading it through the facade. Session auth (no token scopes) and ``*`` tokens
    are unaffected — API scopes never gate session requests, which stay RBAC-only. Everything else
    delegates to the wrapped instance."""

    def __init__(self, inner: UserAccessControl, token_scopes: list[str]) -> None:
        self._inner = inner
        self._token_scopes = token_scopes

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def check_access_level_for_object(self, obj: Any, required_level: Any, *args: Any, **kwargs: Any) -> bool:
        if self._token_lacks_scope_for(obj, required_level):
            return False
        return self._inner.check_access_level_for_object(obj, required_level, *args, **kwargs)

    def _token_lacks_scope_for(self, obj: Any, required_level: Any) -> bool:
        scopes = self._token_scopes
        resource = model_to_resource(obj)
        if "*" in scopes or resource not in _WAREHOUSE_SCOPE_GATED_RESOURCES:
            return False
        if f"{resource}:write" in scopes:
            return False  # write implies read, so it satisfies both viewer and editor
        return not (required_level == "viewer" and f"{resource}:read" in scopes)


def _warehouse_scoped_uac(view: Any) -> UserAccessControl:
    """The view's ``UserAccessControl``, additionally gating warehouse object access on the request
    token's scope for that resource. A no-op for session/other non-token auth (no token scopes)."""
    scopes = get_authenticator_scopes(getattr(view.request, "successful_authenticator", None))
    if scopes is None:
        return view.user_access_control
    return cast(UserAccessControl, _WarehouseScopeGatedAccessControl(view.user_access_control, scopes))


# drf-spectacular auto-describes the pk path param for a model-backed viewset as
# "A UUID string identifying this <model>.". These viewsets reach the model through the
# facade (no ``queryset``), so the description is declared explicitly to keep the generated
# OpenAPI (and MCP) path params byte-identical.
_ACCOUNT_ID_PARAM = OpenApiParameter(
    "id",
    OpenApiTypes.STR,
    OpenApiParameter.PATH,
    description="A UUID string identifying this account.",
)


# NOTE: deliberately no class docstring — a docstring here is inherited as the ViewSets'
# ``__doc__`` and drf-spectacular would surface it as every operation's description (the
# model-backed viewsets had none), drifting the generated clients.
class AccountEmailThreadMessagePagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 200


class _FacadePaginationMixin:
    # Drives the standard ``LimitOffsetPagination`` envelope from a facade ``(page, count)``
    # result. The facade does the slicing (offset/limit), so we set the paginator's state
    # directly rather than handing it a queryset — keeping the param names (``limit`` /
    # ``offset``), default page size, and ``count`` / ``next`` / ``previous`` shape identical
    # to the model-backed viewsets.
    def _paginate_via_facade(self, request: Request, fetch, serializer_class) -> Response:
        paginator = self.paginator  # type: ignore[attr-defined]
        limit = paginator.get_limit(request)
        offset = paginator.get_offset(request)
        page, count = fetch(offset=offset, limit=limit)
        paginator.request = request
        paginator.limit = limit
        paginator.offset = offset
        paginator.count = count
        serializer = serializer_class(instance=page, many=True)
        return paginator.get_paginated_response(serializer.data)


def _object_required_level(request: Request, write: bool) -> str | None:
    """The object-level access level to enforce for this request, or ``None`` when the
    permission layer would skip the object check (service auth) — mirroring
    ``AccessControlPermission.has_object_permission``."""
    if is_service_auth(request):
        return None
    return _OBJECT_WRITE_LEVEL if write else _OBJECT_READ_LEVEL


_GROUP_TARGET_TYPE = "group"


def _has_group_scope(request: Request, *, write: bool) -> bool:
    """Whether the caller may read (``write=False``) or write (``write=True``) the ``group`` resource.
    Group-target custom properties read and modify group data, but these viewsets are scoped to
    ``account`` — so a token/OAuth caller must additionally hold the matching ``group`` scope,
    mirroring what the group API itself enforces. Session callers are governed by project membership
    (same as the group API), and service auth is exempt."""
    if is_service_auth(request):
        return True
    token_scopes = get_authenticator_scopes(getattr(request, "successful_authenticator", None))
    if token_scopes is None:
        return True  # session / non-token auth — same footing as the group API
    if "*" in token_scopes or "group:write" in token_scopes:
        return True
    return not write and "group:read" in token_scopes


def _assert_group_scope(request: Request, *, write: bool) -> None:
    if not _has_group_scope(request, write=write):
        raise PermissionDenied(f"This action requires the `group:{'write' if write else 'read'}` API scope.")


class AccountTrackRuleThrottle(UserRateThrottle):
    scope = "account_track_rules"
    rate = "10/minute"


class AccountTrackRuleViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    _FacadePaginationMixin,
    viewsets.GenericViewSet,
):
    scope_object = "customer_analytics"
    serializer_class = AccountTrackRulesConfigSerializer
    queryset = None
    pagination_class = None
    permission_classes = [PostHogFeatureFlagPermission, TeamMemberStrictManagementPermission]
    posthog_feature_flag = CUSTOMER_ANALYTICS_TRACK_RULES_FLAG

    @classmethod
    def as_view(cls, actions=None, **initkwargs):
        if actions and actions.get("get") == "list":
            actions = {**actions, "put": "update_config"}
        return super().as_view(actions, **initkwargs)

    def dangerously_get_required_scopes(self, _request: Request, _view: Any) -> list[str] | None:
        if self.action == "update_config":
            return ["customer_analytics:write"]
        return None

    @extend_schema(responses={200: AccountTrackRulesConfigSerializer(many=False)})
    def list(self, request: Request, *args, **kwargs) -> Response:
        config = api.get_account_track_rules(self.team_id)
        return Response(AccountTrackRulesConfigSerializer(instance=config).data)

    def _report_usage(self, request: Request, event: str, **properties: Any) -> None:
        report_user_action(cast(User, request.user), event, properties, team=self.team)

    @extend_schema(
        request=AccountTrackRulesConfigSerializer,
        responses={200: AccountTrackRulesConfigSerializer},
    )
    def update_config(self, request: Request, *args, **kwargs) -> Response:
        serializer = AccountTrackRulesConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            config = api.update_account_track_rules(
                team_id=self.team_id,
                raw_config=dict(serializer.validated_data),
                user=cast(User, request.user),
                organization_id=self.organization.id,
                was_impersonated=is_impersonated(request),
            )
        except api.AccountTrackRuleValidationError as error:
            raise ValidationError({"validation_errors": error.errors})
        except api.AccountTrackRuleVersionConflict as error:
            raise Conflict(str(error))
        self._report_usage(
            request,
            "account track rules config saved",
            schema_version=config.schema_version,
            config_version=config.version,
            enabled=config.enabled,
            group_count=len(config.groups),
            condition_count=sum(len(group.conditions) for group in config.groups),
        )
        return Response(AccountTrackRulesConfigSerializer(instance=config).data)

    @extend_schema(
        request=AccountTrackRulesConfigSerializer,
        responses={200: AccountTrackRulePreviewSerializer},
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="preview",
        required_scopes=["customer_analytics:write"],
        throttle_classes=[AccountTrackRuleThrottle],
    )
    def preview(self, request: Request, *args, **kwargs) -> Response:
        raw_config = None
        if request.data:
            serializer = AccountTrackRulesConfigSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            raw_config = dict(serializer.validated_data)
        try:
            preview = api.preview_account_track_rules(self.team_id, raw_config)
        except api.AccountTrackRuleValidationError as error:
            self._report_usage(request, "account track rules preview failed", failure_type="validation")
            raise ValidationError({"validation_errors": error.errors})
        self._report_usage(
            request,
            "account track rules preview completed",
            config_version=preview.config_version,
            eligible_active=preview.eligible_active,
            skipped_churned=preview.skipped_churned,
            tracked=preview.tracked,
            ignored=preview.ignored,
            newly_ignored=preview.newly_ignored,
            restored=preview.restored,
        )
        return Response(AccountTrackRulePreviewSerializer(instance=preview).data)

    @extend_schema(
        request=AccountTrackRuleRunRequestSerializer,
        responses={202: AccountTrackRuleRunSerializer},
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="run",
        required_scopes=["customer_analytics:write"],
        throttle_classes=[AccountTrackRuleThrottle],
    )
    def run(self, request: Request, *args, **kwargs) -> Response:
        serializer = AccountTrackRuleRunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            run, started = api.trigger_account_track_rule_run(
                team_id=self.team_id,
                idempotency_key=data["idempotency_key"],
                user_id=cast(User, request.user).id,
            )
        except api.AccountTrackRuleValidationError as error:
            self._report_usage(request, "account track rules run start failed", failure_type="validation")
            raise ValidationError({"validation_errors": error.errors})
        except api.AccountTrackRuleRunError as error:
            self._report_usage(request, "account track rules run start failed", failure_type="disabled")
            raise ValidationError({"detail": str(error)})
        except api.AccountTrackRuleRunAlreadyActive as error:
            self._report_usage(request, "account track rules run start failed", failure_type="overlap")
            raise Conflict(str(error))
        if started:
            self._report_usage(
                request,
                "account track rules run started",
                config_version=run.config_version,
                trigger=run.trigger,
            )
        return Response(AccountTrackRuleRunSerializer(instance=run).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        responses={200: AccountTrackRuleRunSerializer(many=True)},
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="runs",
        pagination_class=LimitOffsetPagination,
        required_scopes=["customer_analytics:read"],
    )
    def runs(self, request: Request, *args, **kwargs) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_account_track_rule_runs(
                self.team_id,
                offset=offset,
                limit=limit,
            ),
            AccountTrackRuleRunSerializer,
        )


class FeatureRequestProductAreaViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "customer_analytics"
    serializer_class = FeatureRequestProductAreaSerializer
    queryset = None
    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = CUSTOMER_ANALYTICS_FEATURE_REQUESTS_FLAG
    pagination_class = None

    def _require_manager(self) -> None:
        if not self.user_access_control.check_access_level_for_resource("customer_analytics", "manager"):
            raise PermissionDenied("Manager access to Customer Analytics is required to manage product areas.")

    @validated_request(
        query_serializer=FeatureRequestProductAreaListQuerySerializer,
        responses={200: OpenApiResponse(response=FeatureRequestProductAreaSerializer(many=True))},
    )
    def list(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        include_inactive = request.validated_query_data["include_inactive"]
        product_areas = api.list_feature_request_product_areas(
            self.team_id,
            include_inactive=include_inactive,
        )
        return Response(FeatureRequestProductAreaSerializer(instance=product_areas, many=True).data)

    def create(self, request: Request, *args, **kwargs) -> Response:
        self._require_manager()
        serializer = FeatureRequestProductAreaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            product_area = api.create_feature_request_product_area(
                team_id=self.team_id,
                name=data.name,
                display_order=data.display_order,
                actor_id=cast(User, request.user).id,
            )
        except api.FeatureRequestValidationError as error:
            raise ValidationError({error.field: error.message})
        except api.FeatureRequestProductAreaConflictError as error:
            raise Conflict(str(error))
        return Response(FeatureRequestProductAreaSerializer(instance=product_area).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args, **kwargs) -> Response:
        self._require_manager()
        partial = kwargs.pop("partial", False)
        serializer = FeatureRequestProductAreaSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            product_area = api.update_feature_request_product_area(
                team_id=self.team_id,
                product_area_id=self.kwargs["pk"],
                name=data.name if "name" in request.data else None,
                display_order=data.display_order if "display_order" in request.data else None,
                is_active=data.is_active if "is_active" in request.data else None,
                actor_id=cast(User, request.user).id,
            )
        except api.FeatureRequestValidationError as error:
            raise ValidationError({error.field: error.message})
        except api.FeatureRequestProductAreaConflictError as error:
            raise Conflict(str(error))
        if product_area is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(FeatureRequestProductAreaSerializer(instance=product_area).data)

    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)


def _feature_request_evidence_input(data: dict[str, Any] | None) -> contracts.FeatureRequestEvidenceInput | None:
    if data is None:
        return None
    return contracts.FeatureRequestEvidenceInput(
        summary=data["summary"],
        customer_quote=data["customer_quote"],
        evidence_source=data["evidence_source"],
        source_url=data["source_url"],
        requested_on=data["requested_on"],
        image_ids=tuple(data.get("image_ids", ())),
    )


class FeatureRequestViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    _FacadePaginationMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "customer_analytics"
    serializer_class = FeatureRequestSerializer
    queryset = None
    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = CUSTOMER_ANALYTICS_FEATURE_REQUESTS_FLAG

    @validated_request(
        query_serializer=FeatureRequestListQuerySerializer,
        responses={200: OpenApiResponse(response=FeatureRequestSerializer(many=True))},
    )
    def list(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        data = request.validated_query_data
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_feature_requests(
                team_id=self.team_id,
                user_access_control=self.user_access_control,
                filters=contracts.FeatureRequestListFilters(
                    search=data.get("search", ""),
                    statuses=tuple(data.get("statuses", ())),
                    priorities=tuple(data.get("priorities", ())),
                    product_area_ids=tuple(data.get("product_area_ids", ())),
                    account_ids=tuple(data.get("account_ids", ())),
                    created_by_ids=tuple(data.get("created_by_ids", ())),
                    archive_state=data["archive_state"],
                    ordering=data["request_ordering"],
                ),
                offset=offset,
                limit=limit,
            ),
            FeatureRequestSerializer,
        )

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        feature_request = api.get_feature_request(
            team_id=self.team_id,
            feature_request_id=self.kwargs["pk"],
            user_access_control=self.user_access_control,
        )
        if feature_request is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(FeatureRequestSerializer(instance=feature_request).data)

    @extend_schema(
        request=FeatureRequestCreateSerializer,
        responses={200: FeatureRequestSerializer, 201: FeatureRequestSerializer},
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = FeatureRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            outcome = api.create_feature_request(
                team_id=self.team_id,
                input=contracts.CreateFeatureRequestInput(
                    title=data["title"],
                    description=data["description"],
                    account_id=data["account_id"],
                    product_area_ids=tuple(data["product_area_ids"]),
                    idempotency_key=data["idempotency_key"],
                    evidence=_feature_request_evidence_input(data.get("evidence")),
                ),
                actor_id=cast(User, request.user).id,
                user_access_control=self.user_access_control,
            )
        except api.FeatureRequestValidationError as error:
            raise ValidationError({error.field: error.message})
        response_status = status.HTTP_201_CREATED if outcome.created else status.HTTP_200_OK
        return Response(FeatureRequestSerializer(instance=outcome.request).data, status=response_status)

    @extend_schema(request=FeatureRequestUpdateSerializer, responses={200: FeatureRequestSerializer})
    def update(self, request: Request, *args, **kwargs) -> Response:
        serializer = FeatureRequestUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            feature_request = api.update_feature_request(
                team_id=self.team_id,
                feature_request_id=self.kwargs["pk"],
                input=contracts.UpdateFeatureRequestInput(
                    expected_version=data["expected_version"],
                    title=data.get("title"),
                    description=data.get("description"),
                    account_ids=(
                        tuple(data["account_ids"])
                        if "account_ids" in request.data
                        else ((data["account_id"],) if "account_id" in request.data else None)
                    ),
                    product_area_ids=(tuple(data["product_area_ids"]) if "product_area_ids" in request.data else None),
                    request_status=data.get("request_status"),
                    request_priority=data.get("request_priority"),
                    request_priority_is_set="request_priority" in request.data,
                ),
                actor_id=cast(User, request.user).id,
                user_access_control=self.user_access_control,
            )
        except api.FeatureRequestValidationError as error:
            raise ValidationError({error.field: error.message})
        except api.FeatureRequestConflictError as error:
            raise Conflict(str(error))
        if feature_request is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(FeatureRequestSerializer(instance=feature_request).data)

    @extend_schema(request=FeatureRequestUpdateSerializer, responses={200: FeatureRequestSerializer})
    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        return self.update(request, *args, **kwargs)

    @extend_schema(request=FeatureRequestAddAccountSerializer, responses={200: FeatureRequestSerializer})
    @action(methods=["POST"], detail=True, required_scopes=["customer_analytics:write"])
    def add_account(self, request: Request, *args, **kwargs) -> Response:
        serializer = FeatureRequestAddAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        evidence = _feature_request_evidence_input(data.get("evidence"))
        try:
            feature_request = api.add_feature_request_account(
                team_id=self.team_id,
                feature_request_id=self.kwargs["pk"],
                input=contracts.AddFeatureRequestAccountInput(
                    expected_version=data["expected_version"],
                    account_id=data["account_id"],
                    evidence=evidence,
                ),
                actor_id=cast(User, request.user).id,
                user_access_control=self.user_access_control,
            )
        except api.FeatureRequestValidationError as error:
            raise ValidationError({error.field: error.message})
        except api.FeatureRequestConflictError as error:
            raise Conflict(str(error))
        if feature_request is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(FeatureRequestSerializer(instance=feature_request).data)

    @extend_schema(request=FeatureRequestEvidenceCreateSerializer, responses={200: FeatureRequestSerializer})
    @action(methods=["POST"], detail=True, required_scopes=["customer_analytics:write"])
    def add_evidence(self, request: Request, *args, **kwargs) -> Response:
        serializer = FeatureRequestEvidenceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            feature_request = api.create_feature_request_evidence(
                team_id=self.team_id,
                feature_request_id=self.kwargs["pk"],
                input=contracts.CreateFeatureRequestEvidenceInput(
                    expected_version=data["expected_version"],
                    account_link_id=data["account_link_id"],
                    summary=data["summary"],
                    customer_quote=data["customer_quote"],
                    evidence_source=data["evidence_source"],
                    source_url=data["source_url"],
                    requested_on=data["requested_on"],
                    image_ids=tuple(data.get("image_ids", ())),
                ),
                actor_id=cast(User, request.user).id,
                user_access_control=self.user_access_control,
            )
        except api.FeatureRequestValidationError as error:
            raise ValidationError({error.field: error.message})
        except api.FeatureRequestConflictError as error:
            raise Conflict(str(error))
        if feature_request is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(FeatureRequestSerializer(instance=feature_request).data)

    @extend_schema(request=FeatureRequestEvidenceUpdateSerializer, responses={200: FeatureRequestSerializer})
    @action(methods=["POST"], detail=True, required_scopes=["customer_analytics:write"])
    def update_evidence(self, request: Request, *args, **kwargs) -> Response:
        serializer = FeatureRequestEvidenceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            feature_request = api.update_feature_request_evidence(
                team_id=self.team_id,
                feature_request_id=self.kwargs["pk"],
                input=contracts.UpdateFeatureRequestEvidenceInput(
                    expected_version=data["expected_version"],
                    evidence_id=data["evidence_id"],
                    summary=data["summary"],
                    customer_quote=data["customer_quote"],
                    evidence_source=data["evidence_source"],
                    source_url=data["source_url"],
                    requested_on=data["requested_on"],
                    image_ids=tuple(data["image_ids"]) if "image_ids" in request.data else None,
                ),
                actor_id=cast(User, request.user).id,
                user_access_control=self.user_access_control,
            )
        except api.FeatureRequestValidationError as error:
            raise ValidationError({error.field: error.message})
        except api.FeatureRequestConflictError as error:
            raise Conflict(str(error))
        if feature_request is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(FeatureRequestSerializer(instance=feature_request).data)

    @extend_schema(request=FeatureRequestEvidenceDeleteSerializer, responses={200: FeatureRequestSerializer})
    @action(methods=["POST"], detail=True, required_scopes=["customer_analytics:write"])
    def remove_evidence(self, request: Request, *args, **kwargs) -> Response:
        serializer = FeatureRequestEvidenceDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            feature_request = api.delete_feature_request_evidence(
                team_id=self.team_id,
                feature_request_id=self.kwargs["pk"],
                input=contracts.DeleteFeatureRequestEvidenceInput(
                    expected_version=data["expected_version"],
                    evidence_id=data["evidence_id"],
                ),
                actor_id=cast(User, request.user).id,
                user_access_control=self.user_access_control,
            )
        except api.FeatureRequestValidationError as error:
            raise ValidationError({error.field: error.message})
        except api.FeatureRequestConflictError as error:
            raise Conflict(str(error))
        if feature_request is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(FeatureRequestSerializer(instance=feature_request).data)

    def _set_archived(self, request: Request, *, archived: bool) -> Response:
        serializer = FeatureRequestVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            feature_request = api.set_feature_request_archived(
                team_id=self.team_id,
                feature_request_id=self.kwargs["pk"],
                expected_version=serializer.validated_data["expected_version"],
                archived=archived,
                actor_id=cast(User, request.user).id,
                user_access_control=self.user_access_control,
            )
        except api.FeatureRequestConflictError as error:
            raise Conflict(str(error))
        if feature_request is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(FeatureRequestSerializer(instance=feature_request).data)

    @extend_schema(request=FeatureRequestVersionSerializer, responses={200: FeatureRequestSerializer})
    @action(methods=["POST"], detail=True, required_scopes=["customer_analytics:write"])
    def archive(self, request: Request, *args, **kwargs) -> Response:
        return self._set_archived(request, archived=True)

    @extend_schema(request=FeatureRequestVersionSerializer, responses={200: FeatureRequestSerializer})
    @action(methods=["POST"], detail=True, required_scopes=["customer_analytics:write"])
    def restore(self, request: Request, *args, **kwargs) -> Response:
        return self._set_archived(request, archived=False)

    @extend_schema(responses={200: FeatureRequestHistorySerializer(many=True)})
    @action(methods=["GET"], detail=True, pagination_class=None, required_scopes=["customer_analytics:read"])
    def history(self, request: Request, *args, **kwargs) -> Response:
        history = api.list_feature_request_history(
            team_id=self.team_id,
            feature_request_id=self.kwargs["pk"],
            user_access_control=self.user_access_control,
        )
        if history is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(FeatureRequestHistorySerializer(instance=history, many=True).data)

    @extend_schema(responses={200: FeatureRequestStatusHistorySerializer(many=True)})
    @action(methods=["GET"], detail=True, pagination_class=None, required_scopes=["customer_analytics:read"])
    def status_history(self, request: Request, *args, **kwargs) -> Response:
        history = api.list_feature_request_status_history(
            team_id=self.team_id,
            feature_request_id=self.kwargs["pk"],
            user_access_control=self.user_access_control,
        )
        if history is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(FeatureRequestStatusHistorySerializer(instance=history, many=True).data)


class CustomerProfileConfigViewSet(
    TeamAndOrgViewSetMixin,
    _FacadePaginationMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "customer_profile_config"
    serializer_class = CustomerProfileConfigSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only

    def list(self, request: Request, *args, **kwargs) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_customer_profile_configs(self.team_id, offset=offset, limit=limit),
            CustomerProfileConfigSerializer,
        )

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        config = api.get_customer_profile_config(self.team_id, self.kwargs["pk"])
        if config is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CustomerProfileConfigSerializer(instance=config).data)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = CustomerProfileConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        config = api.create_customer_profile_config(
            team_id=self.team_id,
            scope=data.scope,
            content=data.content,
            sidebar=data.sidebar,
            organization_id=self.organization.id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
        )
        return Response(CustomerProfileConfigSerializer(instance=config).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args, **kwargs) -> Response:
        partial = kwargs.pop("partial", False)
        serializer = CustomerProfileConfigSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        config = api.update_customer_profile_config(
            team_id=self.team_id,
            config_id=self.kwargs["pk"],
            fields=_profile_config_write_fields(serializer.validated_data, request.data),
            organization_id=self.organization.id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
        )
        if config is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CustomerProfileConfigSerializer(instance=config).data)

    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        deleted = api.delete_customer_profile_config(
            team_id=self.team_id,
            config_id=self.kwargs["pk"],
            organization_id=self.organization.id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
        )
        if not deleted:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _profile_config_write_fields(validated, raw_data: dict) -> dict:
    """The profile-config columns the caller actually sent (scope/content/sidebar). ``content``
    and ``sidebar`` default to ``{}`` in the serializer, so only forward them when present in
    the raw body — matching the model serializer's partial-update behavior."""
    fields: dict = {}
    if "scope" in raw_data:
        fields["scope"] = validated.scope
    if "content" in raw_data:
        fields["content"] = validated.content
    if "sidebar" in raw_data:
        fields["sidebar"] = validated.sidebar
    return fields


class CustomPropertyDefinitionViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    _FacadePaginationMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "account"
    permission_classes = [TeamMemberLightManagementPermission]
    # ``values`` is a custom read action; without listing it here it carries no required scope and
    # rejects token auth outright ("does not support personal API key access") before the group gate runs.
    scope_object_read_actions = ["list", "retrieve", "values"]
    serializer_class = CustomPropertyDefinitionSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only

    def list(self, request: Request, *args, **kwargs) -> Response:
        # Callers without group read authorization don't see group-target definitions.
        exclude_group_targets = not _has_group_scope(request, write=False)
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_custom_property_definitions(
                self.team_id,
                offset=offset,
                limit=limit,
                user_access_control=_warehouse_scoped_uac(self),
                exclude_group_targets=exclude_group_targets,
            ),
            CustomPropertyDefinitionSerializer,
        )

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        definition = api.get_custom_property_definition(
            self.team_id, self.kwargs["pk"], user_access_control=_warehouse_scoped_uac(self)
        )
        # Hide group-target definitions from callers without group read authorization.
        if definition is None or (
            definition.target_type == _GROUP_TARGET_TYPE and not _has_group_scope(request, write=False)
        ):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CustomPropertyDefinitionSerializer(instance=definition).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="key",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Id of the custom property definition to suggest values for.",
            ),
            OpenApiParameter(
                name="value",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Case-insensitive substring to narrow the suggestions.",
            ),
        ],
        responses={200: CustomPropertyValueSuggestionsResponseSerializer},
    )
    @action(methods=["GET"], detail=False, pagination_class=None)
    def values(self, request: Request, *args, **kwargs) -> Response:
        key = request.GET.get("key")
        if not key:
            return Response({"results": [], "refreshing": False})
        # Suggestions expose a group-target definition's option labels (and its existence), so gate them
        # on group read authorization just like list/retrieve — an account-scoped caller without group
        # read must not read group property configuration. Unknown keys keep the empty-envelope behavior.
        definition = api.get_custom_property_definition(
            self.team_id, key, user_access_control=_warehouse_scoped_uac(self)
        )
        if (
            definition is not None
            and definition.target_type == _GROUP_TARGET_TYPE
            and not _has_group_scope(request, write=False)
        ):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        suggestions = api.list_custom_property_value_suggestions(self.team_id, key, request.GET.get("value"))
        return Response({"results": [{"name": value} for value in suggestions], "refreshing": False})

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = CustomPropertyDefinitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # Person and group targets are both gated behind the warehouse-person-properties rollout flag.
        if data.target_type in ("person", "group") and not api.person_properties_flag_enabled(self.team_id):
            raise ValidationError({"target_type": "Person/group properties from warehouse data are not enabled yet."})
        if data.target_type == _GROUP_TARGET_TYPE:
            _assert_group_scope(request, write=True)
        try:
            definition = api.create_custom_property_definition(
                team_id=self.team_id,
                name=data.name,
                description=data.description,
                display_type=data.display_type,
                is_big_number=data.is_big_number,
                options=_custom_property_option_dicts(data.options),
                target_type=data.target_type,
                group_type_index=data.group_type_index,
                organization_id=self.organization.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except api.CustomPropertyDefinitionConflictError as e:
            raise Conflict(str(e))
        except api.InvalidCustomPropertyOptions as e:
            raise ValidationError({"options": str(e)})
        return Response(CustomPropertyDefinitionSerializer(instance=definition).data, status=status.HTTP_201_CREATED)

    def _guard_group_definition(self, request: Request, definition_id) -> None:
        # Group-target definitions gate the group-writing pipeline, so mutating one needs group scope.
        definition = api.get_custom_property_definition(
            self.team_id, definition_id, user_access_control=self.user_access_control
        )
        if definition is not None and definition.target_type == _GROUP_TARGET_TYPE:
            _assert_group_scope(request, write=True)

    def update(self, request: Request, *args, **kwargs) -> Response:
        self._guard_group_definition(request, self.kwargs["pk"])
        partial = kwargs.pop("partial", False)
        serializer = CustomPropertyDefinitionSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            definition = api.update_custom_property_definition(
                team_id=self.team_id,
                definition_id=self.kwargs["pk"],
                fields=_custom_property_definition_write_fields(serializer.validated_data, request.data),
                organization_id=self.organization.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
                user_access_control=_warehouse_scoped_uac(self),
            )
        except api.CustomPropertyDefinitionConflictError as e:
            raise Conflict(str(e))
        except api.CanonicalCustomPropertyReadOnlyError as e:
            raise ValidationError(str(e))
        except api.InvalidCustomPropertyOptions as e:
            raise ValidationError({"options": str(e)})
        if definition is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CustomPropertyDefinitionSerializer(instance=definition).data)

    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        self._guard_group_definition(request, self.kwargs["pk"])
        deleted = api.delete_custom_property_definition(
            team_id=self.team_id,
            definition_id=self.kwargs["pk"],
            organization_id=self.organization.id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
        )
        if not deleted:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _custom_property_definition_write_fields(validated, raw_data: dict) -> dict:
    """The columns the caller actually sent. ``is_big_number`` is re-derived in the facade against
    the effective display type, so a PATCH that omits it still clears it for a non-numeric type."""
    fields: dict = {}
    if "name" in raw_data:
        fields["name"] = validated.name
    if "description" in raw_data:
        fields["description"] = validated.description
    if "display_type" in raw_data:
        fields["display_type"] = validated.display_type
    if "is_big_number" in raw_data:
        fields["is_big_number"] = validated.is_big_number
    if "options" in raw_data:
        fields["options"] = _custom_property_option_dicts(validated.options)
    return fields


def _custom_property_option_dicts(options) -> list[dict] | None:
    """Nested DataclassSerializer fields validate into dataclass instances; the facade and the
    JSONField speak plain dicts."""
    if options is None:
        return None
    return [asdict(option) for option in options]


class AccountRelationshipDefinitionViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    _FacadePaginationMixin,
    viewsets.ModelViewSet,
):
    scope_object = "account"
    serializer_class = AccountRelationshipDefinitionSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only

    def list(self, request: Request, *args, **kwargs) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_account_relationship_definitions(self.team_id, offset=offset, limit=limit),
            AccountRelationshipDefinitionSerializer,
        )

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        definition = api.get_account_relationship_definition(self.team_id, self.kwargs["pk"])
        if definition is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AccountRelationshipDefinitionSerializer(instance=definition).data)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = AccountRelationshipDefinitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            definition = api.create_account_relationship_definition(
                team_id=self.team_id,
                name=data.name,
                description=data.description,
                is_single_holder=data.is_single_holder,
                created_by=cast(User, request.user),
            )
        except api.AccountRelationshipDefinitionConflictError as e:
            raise Conflict(str(e))
        return Response(
            AccountRelationshipDefinitionSerializer(instance=definition).data, status=status.HTTP_201_CREATED
        )

    def update(self, request: Request, *args, **kwargs) -> Response:
        partial = kwargs.pop("partial", False)
        serializer = AccountRelationshipDefinitionSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            definition = api.update_account_relationship_definition(
                team_id=self.team_id,
                definition_id=self.kwargs["pk"],
                fields=_account_relationship_definition_write_fields(serializer.validated_data, request.data),
            )
        except api.AccountRelationshipDefinitionConflictError as e:
            raise Conflict(str(e))
        if definition is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AccountRelationshipDefinitionSerializer(instance=definition).data)

    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        if not api.delete_account_relationship_definition(team_id=self.team_id, definition_id=self.kwargs["pk"]):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _account_relationship_definition_write_fields(validated, raw_data: dict) -> dict:
    fields: dict = {}
    if "name" in raw_data:
        fields["name"] = validated.name
    if "description" in raw_data:
        fields["description"] = validated.description
    if "is_single_holder" in raw_data:
        fields["is_single_holder"] = validated.is_single_holder
    return fields


class CustomPropertySourceSyncThrottle(RunSavedQueryRateThrottle):
    """A manual sync starts a real warehouse run — a billable import for a table binding, a
    materialization for a view. Keying on the bound warehouse object instead of the mapping puts a
    view-bound sync in the same bucket as the canonical saved-query run endpoint, so a caller can't
    exceed that view's run limit by pointing two mappings at it (or by using this route instead)."""

    def get_cache_key(self, request, view):
        team_id = self.safely_get_team_id_from_view(view)
        source_id = view.kwargs.get("pk", "")
        if team_id and source_id:
            binding_id = api.get_custom_property_source_binding_id(team_id, source_id)
            if binding_id:
                return self.cache_format % {"scope": self.scope, "ident": f"{team_id}_{binding_id}"}
        return super().get_cache_key(request, view)


class CustomPropertySourceViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    _FacadePaginationMixin,
    viewsets.ModelViewSet,
):
    scope_object = "account"
    serializer_class = CustomPropertySourceSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only

    def list(self, request: Request, *args, **kwargs) -> Response:
        # Callers without group read authorization don't see sources feeding group-target definitions.
        exclude_group_targets = not _has_group_scope(request, write=False)
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_custom_property_sources(
                self.team_id,
                offset=offset,
                limit=limit,
                user_access_control=_warehouse_scoped_uac(self),
                exclude_group_targets=exclude_group_targets,
            ),
            CustomPropertySourceSerializer,
        )

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        source = api.get_custom_property_source(
            self.team_id, self.kwargs["pk"], user_access_control=_warehouse_scoped_uac(self)
        )
        # Hide sources feeding a group-target definition from callers without group read authorization.
        if source is None or (
            self._definition_is_group(source.definition) and not _has_group_scope(request, write=False)
        ):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CustomPropertySourceSerializer(instance=source).data)

    def _definition_target_type(self, definition_id) -> str | None:
        if definition_id is None:
            return None
        definition = api.get_custom_property_definition(
            self.team_id, str(definition_id), user_access_control=self.user_access_control
        )
        return definition.target_type if definition is not None else None

    def _definition_is_group(self, definition_id) -> bool:
        return self._definition_target_type(definition_id) == _GROUP_TARGET_TYPE

    def _report_usage(self, request: Request, event: str, **properties: Any) -> None:
        # The scene's $pageview says who looked at Warehouse properties; these say who actually
        # mapped a table. Emitted here rather than in the frontend so API callers count too.
        report_user_action(cast(User, request.user), event, properties, team=self.team)

    def _guard_group_source(self, request: Request, source_id, *, write: bool = True) -> None:
        # A source feeding a group definition reads/activates the group-writing pipeline, so touching
        # it needs group scope — an account-only token must not read or modify group properties.
        source = api.get_custom_property_source(self.team_id, source_id)
        if source is not None and self._definition_is_group(source.definition):
            _assert_group_scope(request, write=write)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = CustomPropertySourceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        target_type = self._definition_target_type(data.definition)
        if target_type == _GROUP_TARGET_TYPE:
            _assert_group_scope(request, write=True)
        try:
            source = api.create_custom_property_source(
                team_id=self.team_id,
                definition_id=data.definition,
                saved_query_id=data.saved_query,
                source_column=data.source_column,
                external_data_schema_id=data.external_data_schema,
                column_property_map=data.column_property_map,
                column_descriptions=data.column_descriptions,
                key_column=data.key_column,
                is_enabled=data.is_enabled,
                user=cast(User, request.user),
                user_access_control=_warehouse_scoped_uac(self),
            )
        except api.CustomPropertySourceValidationError as e:
            raise ValidationError(str(e))
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        self._report_usage(
            request,
            "warehouse property mapping created",
            target_type=target_type,
            mapped_column_count=len(data.column_property_map or {}),
            reads_warehouse_table=data.external_data_schema is not None,
            is_enabled=data.is_enabled,
        )
        return Response(CustomPropertySourceSerializer(instance=source).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=CustomPropertySourceUpdateSerializer)
    def update(self, request: Request, *args, **kwargs) -> Response:
        self._guard_group_source(request, self.kwargs["pk"])
        write = CustomPropertySourceUpdateSerializer(data=request.data, partial=kwargs.pop("partial", False))
        write.is_valid(raise_exception=True)
        try:
            source = api.update_custom_property_source(
                team_id=self.team_id,
                source_id=self.kwargs["pk"],
                fields=write.validated_data,
                user_access_control=_warehouse_scoped_uac(self),
            )
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        if source is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        self._report_usage(
            request,
            "warehouse property mapping updated",
            updated_fields=sorted(write.validated_data.keys()),
            is_enabled=source.is_enabled,
        )
        return Response(CustomPropertySourceSerializer(instance=source).data)

    @extend_schema(request=CustomPropertySourceUpdateSerializer)
    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        self._guard_group_source(request, self.kwargs["pk"])
        try:
            deleted = api.delete_custom_property_source(
                team_id=self.team_id,
                source_id=self.kwargs["pk"],
                user_access_control=_warehouse_scoped_uac(self),
            )
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        if not deleted:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        self._report_usage(request, "warehouse property mapping deleted")
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="custom_property_sources_sync",
        request=None,
        responses={202: CustomPropertySyncTriggerResponseSerializer},
    )
    @action(methods=["POST"], detail=True, throttle_classes=[CustomPropertySourceSyncThrottle])
    def sync(self, request: Request, *args, **kwargs) -> Response:
        """Person and group sources only: run what this source reads now — an import for a table
        binding (a real, billable warehouse sync), a materialization for a view binding. The
        incremental person/group-property update runs off that run."""
        self._guard_group_source(request, self.kwargs["pk"])
        try:
            triggered = api.trigger_person_property_sync(
                team_id=self.team_id, source_id=self.kwargs["pk"], user_access_control=_warehouse_scoped_uac(self)
            )
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        except (api.WarehouseSyncPausedError, api.ViewNotSyncableError) as e:
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        if not triggered:
            raise ValidationError("This action is only available for enabled person- or group-property sources.")
        self._report_usage(request, "warehouse property sync triggered")
        return Response({"status": "triggered"}, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        operation_id="custom_property_sources_backfill",
        request=None,
        responses={202: CustomPropertySyncTriggerResponseSerializer},
    )
    @action(methods=["POST"], detail=True)
    def backfill(self, request: Request, *args, **kwargs) -> Response:
        """Person and group sources only: start a backfill that reads the whole warehouse table and
        populates person or group properties for historical rows. Coalesces if one is already running
        for the table."""
        self._guard_group_source(request, self.kwargs["pk"])
        try:
            started = api.trigger_person_property_backfill(
                team_id=self.team_id,
                source_id=self.kwargs["pk"],
                trigger="manual",
                user_access_control=_warehouse_scoped_uac(self),
            )
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        if started is None:
            raise ValidationError("This action is only available for enabled person- or group-property sources.")
        self._report_usage(request, "warehouse property backfill triggered", already_running=not started)
        return Response(
            {"status": "started" if started else "already_running", "already_running": not started},
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        operation_id="custom_property_sources_runs_list",
        parameters=[CustomPropertySyncRunListQuerySerializer],
        responses={200: CustomPropertySyncRunSerializer(many=True)},
    )
    @action(methods=["GET"], detail=True)
    def runs(self, request: Request, *args, **kwargs) -> Response:
        """The source's sync history, newest first. Person and group runs require viewer access to
        their warehouse source because the response includes row counts and sync errors."""
        # Hide the run history of a group-target source from callers without group read authorization.
        source = api.get_custom_property_source(self.team_id, self.kwargs["pk"])
        if (
            source is not None
            and self._definition_is_group(source.definition)
            and not _has_group_scope(request, write=False)
        ):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if source is not None and self._definition_target_type(source.definition) == "account":
            self._report_usage(request, "account property sync history viewed")
        query = CustomPropertySyncRunListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        search = query.validated_data.get("search", "").strip() or None
        try:
            return self._paginate_via_facade(
                request,
                lambda offset, limit: api.list_custom_property_sync_runs(
                    self.team_id,
                    self.kwargs["pk"],
                    offset=offset,
                    limit=limit,
                    user_access_control=_warehouse_scoped_uac(self),
                    include_temporal_urls=bool(request.user.is_staff or is_impersonated(request)),
                    search=search,
                ),
                CustomPropertySyncRunSerializer,
            )
        except api.ResourceForbiddenError:
            raise PermissionDenied()


class CustomerJourneyViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    _FacadePaginationMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "customer_journey"
    serializer_class = CustomerJourneySerializer
    queryset = None

    def list(self, request: Request, *args, **kwargs) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_customer_journeys(
                self.team_id, offset=offset, limit=limit, user_access_control=self.user_access_control
            ),
            CustomerJourneySerializer,
        )

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        try:
            journey = api.get_customer_journey(
                self.team_id,
                self.kwargs["pk"],
                user_access_control=self.user_access_control,
                required_level=_object_required_level(request, write=False),
            )
        except api.CustomerJourney_DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        return Response(CustomerJourneySerializer(instance=journey).data)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = CustomerJourneySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not api.insight_belongs_to_team(self.team_id, data.insight):
            raise ValidationError({"insight": "The insight does not belong to this team."})
        try:
            journey = api.create_customer_journey(
                team_id=self.team_id,
                insight_id=data.insight,
                name=data.name,
                description=data.description,
                organization_id=self.organization.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except api.CustomerJourneyConflictError as e:
            raise Conflict(str(e))
        return Response(CustomerJourneySerializer(instance=journey).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args, **kwargs) -> Response:
        partial = kwargs.pop("partial", False)
        serializer = CustomerJourneySerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "insight" in request.data and not api.insight_belongs_to_team(self.team_id, data.insight):
            raise ValidationError({"insight": "The insight does not belong to this team."})
        try:
            journey = api.update_customer_journey(
                team_id=self.team_id,
                journey_id=self.kwargs["pk"],
                fields=_journey_write_fields(data, request.data),
                user_access_control=self.user_access_control,
                required_level=_object_required_level(request, write=True),
                organization_id=self.organization.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except api.CustomerJourney_DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        return Response(CustomerJourneySerializer(instance=journey).data)

    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        try:
            api.delete_customer_journey(
                team_id=self.team_id,
                journey_id=self.kwargs["pk"],
                user_access_control=self.user_access_control,
                required_level=_object_required_level(request, write=True),
                organization_id=self.organization.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except api.CustomerJourney_DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _journey_write_fields(validated, raw_data: dict) -> dict:
    fields: dict = {}
    if "name" in raw_data:
        fields["name"] = validated.name
    if "description" in raw_data:
        fields["description"] = validated.description
    if "insight" in raw_data:
        fields["insight_id"] = validated.insight
    return fields


def _parse_tags_param(request: Request) -> list[str] | None:
    tags_param = request.query_params.get("tags")
    if not tags_param:
        return None
    try:
        tags_list = json.loads(tags_param)
    except json.JSONDecodeError:
        raise ValidationError({"tags": "Must be a JSON-encoded list of strings."})
    if not isinstance(tags_list, list) or not all(isinstance(t, str) for t in tags_list):
        raise ValidationError({"tags": "Must be a JSON-encoded list of strings."})
    return tags_list


class AccountViewSet(
    TaggedItemViewSetMixin,
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    _FacadePaginationMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "account"
    serializer_class = AccountSerializer
    queryset = None
    bulk_update_tags = None  # Mixin action assumes integer PKs; Account uses UUIDs.

    ALLOWED_ORDERING = frozenset({"name", "-name", "created_at", "-created_at", "updated_at", "-updated_at"})

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Case-insensitive substring search across account name and external ID.",
            ),
            OpenApiParameter(
                name="tags",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    'JSON-encoded array of tag names to filter by, e.g. `["enterprise","priority"]`. '
                    "Returns accounts that have any of the listed tags. "
                    "Malformed values (not a JSON-encoded list of strings) return a 400."
                ),
            ),
            OpenApiParameter(
                name="all_roles_unassigned",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description="When true, returns only accounts where no user actively holds any relationship.",
            ),
            OpenApiParameter(
                name="include_churned",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                default=False,
                description="Include churned accounts. Churned accounts are hidden by default.",
            ),
            OpenApiParameter(
                name="include_ignored",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                default=False,
                description="Include ignored accounts. Ignored accounts are hidden by default.",
            ),
            OpenApiParameter(
                name="ordering",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["name", "-name", "created_at", "-created_at", "updated_at", "-updated_at"],
                description="Sort order. Defaults to '-created_at'.",
            ),
        ],
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        tags = _parse_tags_param(self.request)
        ordering = request.query_params.get("ordering")
        ordering = ordering if ordering in self.ALLOWED_ORDERING else None
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_accounts_for_view(
                team_id=self.team_id,
                user_access_control=self.user_access_control,
                offset=offset,
                limit=limit,
                search=request.query_params.get("search", "").strip() or None,
                tags=tags,
                all_roles_unassigned=request.query_params.get("all_roles_unassigned", "").lower() == "true",
                include_churned=request.query_params.get("include_churned", "").lower() == "true",
                include_ignored=request.query_params.get("include_ignored", "").lower() == "true",
                ordering=ordering,
            ),
            AccountSerializer,
        )

    @extend_schema(parameters=[_ACCOUNT_ID_PARAM])
    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        try:
            account = api.get_account_for_view(
                team_id=self.team_id,
                account_id=self.kwargs["pk"],
                user_access_control=self.user_access_control,
                required_level=_object_required_level(request, write=False),
            )
        except api.Account_DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        return Response(AccountSerializer(instance=account).data)

    @extend_schema(parameters=[_ACCOUNT_ID_PARAM], responses={200: SupportTicketSerializer(many=True)})
    @action(methods=["GET"], detail=True, pagination_class=None)
    def support_tickets(self, request: Request, *args, **kwargs) -> Response:
        try:
            tickets = api.get_account_support_tickets(
                self.team_id,
                self.kwargs["pk"],
                user_access_control=self.user_access_control,
            )
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        if tickets is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(SupportTicketSerializer(instance=tickets, many=True).data)

    @extend_schema(
        operation_id="accounts_support_ticket_messages_list",
        parameters=[_ACCOUNT_ID_PARAM],
        responses={200: SupportTicketMessageSerializer(many=True)},
    )
    @action(
        methods=["GET"],
        detail=True,
        url_path=r"support_tickets/(?P<ticket_id>[^/.]+)",
        url_name="support-ticket-detail",
        pagination_class=AccountEmailThreadMessagePagination,
    )
    def support_ticket(self, request: Request, ticket_id: str, *args, **kwargs) -> Response:
        try:
            parsed_ticket_id = str(UUID(ticket_id))
        except ValueError:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        paginator = cast(LimitOffsetPagination, self.paginator)
        limit = paginator.get_limit(request)
        assert limit is not None
        offset = paginator.get_offset(request)
        try:
            result = api.get_account_support_ticket_messages(
                self.team_id,
                self.kwargs["pk"],
                parsed_ticket_id,
                self.user_access_control,
                offset=offset,
                limit=limit,
            )
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        if result is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        messages, count = result
        paginator.request = request
        paginator.limit = limit
        paginator.offset = offset
        paginator.count = count
        serializer = SupportTicketMessageSerializer(instance=messages, many=True)
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(parameters=[_ACCOUNT_ID_PARAM], responses={200: AccountEmailThreadSerializer(many=True)})
    @action(methods=["GET"], detail=True, url_path="email_threads")
    def email_threads(self, request: Request, *args, **kwargs) -> Response:
        if api.get_accessible_account_id(self.team_id, self.kwargs["pk"], self.user_access_control) is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        def fetch(offset: int, limit: int) -> tuple[list[api.AccountEmailThreadSummary], int]:
            try:
                result = api.get_account_email_threads(
                    self.team_id,
                    self.kwargs["pk"],
                    self.user_access_control,
                    offset=offset,
                    limit=limit,
                )
            except api.ResourceForbiddenError:
                raise PermissionDenied()
            return result if result is not None else ([], 0)

        return self._paginate_via_facade(request, fetch, AccountEmailThreadSerializer)

    @extend_schema(
        operation_id="accounts_email_thread_messages_list",
        parameters=[_ACCOUNT_ID_PARAM],
        responses={200: AccountEmailThreadMessageSerializer(many=True)},
    )
    @action(
        methods=["GET"],
        detail=True,
        url_path=r"email_threads/(?P<thread_id>[^/.]+)",
        url_name="email-thread-detail",
        pagination_class=AccountEmailThreadMessagePagination,
    )
    def email_thread(self, request: Request, thread_id: str, *args, **kwargs) -> Response:
        try:
            parsed_thread_id = str(UUID(thread_id))
        except ValueError:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        paginator = cast(LimitOffsetPagination, self.paginator)
        limit = paginator.get_limit(request)
        assert limit is not None
        offset = paginator.get_offset(request)
        try:
            result = api.get_account_email_thread_messages(
                self.team_id,
                self.kwargs["pk"],
                parsed_thread_id,
                self.user_access_control,
                offset=offset,
                limit=limit,
            )
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        if result is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        messages, count = result
        paginator.request = request
        paginator.limit = limit
        paginator.offset = offset
        paginator.count = count
        serializer = AccountEmailThreadMessageSerializer(instance=messages, many=True)
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        parameters=[
            _ACCOUNT_ID_PARAM,
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter meetings by title or attendee email/name.",
            ),
        ],
        responses={200: MeetingSerializer(many=True)},
    )
    @action(methods=["GET"], detail=True)
    def meetings(self, request: Request, *args, **kwargs) -> Response:
        if api.get_accessible_account_id(self.team_id, self.kwargs["pk"], self.user_access_control) is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        search = request.query_params.get("search", "").strip() or None

        def fetch(offset: int, limit: int) -> tuple[list[contracts.MeetingView], int]:
            result = api.list_account_meetings(
                self.team_id,
                self.kwargs["pk"],
                self.user_access_control,
                offset=offset,
                limit=limit,
                search=search,
            )
            return result if result is not None else ([], 0)

        return self._paginate_via_facade(request, fetch, MeetingSerializer)

    def dangerously_get_required_scopes(self, request: Request, view) -> builtins.list[str] | None:
        super_method = getattr(super(), "dangerously_get_required_scopes", None)
        if callable(super_method):
            mixin_result = super_method(request, view)
            if mixin_result is not None:
                return mixin_result
        # Ticket content behind an account-scoped viewset — a token holding only
        # account:read must not read it.
        if view.action in {"support_tickets", "support_ticket", "email_threads", "email_thread"}:
            return ["account:read", "ticket:read"]
        return None

    # Image bytes for <img src>; deliberately outside the typed client surface.
    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=False, required_scopes=["account:read"])
    def icon(self, request: Request, *args, **kwargs) -> HttpResponse:
        domain = request.query_params.get("domain", "").strip().lower().rstrip(".")
        try:
            _ICON_DOMAIN_VALIDATOR(domain)
        except DjangoValidationError:
            raise ValidationError("domain must be a bare hostname, e.g. posthog.com")
        theme = request.query_params.get("theme")
        return CDPIconsService().get_icon_http_response(
            domain,
            # Bound cache keys to the themes logo.dev supports.
            theme=theme if theme in ("light", "dark") else None,
            # AccountLogo renders its own lettermark on 404 instead of logo.dev's monogram.
            fallback="404",
            team_id=self.team_id,
        )

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = AccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            account = api.create_account_for_view(
                team=self.team,
                input=contracts.CreateAccountInput(
                    name=data.name,
                    external_id=data.external_id,
                    properties=data.properties or {},
                    tags=_account_tags_input(serializer),
                    slack_summary_cadence=data.slack_summary_cadence,
                    churned_at=data.churned_at,
                ),
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except api.AccountPropertiesValidationError as e:
            raise ValidationError({"properties": e.messages})
        except api.AccountConflictError as e:
            raise Conflict(str(e))
        return Response(AccountSerializer(instance=account).data, status=status.HTTP_201_CREATED)

    @extend_schema(parameters=[_ACCOUNT_ID_PARAM])
    def update(self, request: Request, *args, **kwargs) -> Response:
        partial = kwargs.pop("partial", False)
        serializer = AccountSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        membership_level = self.user_permissions.current_team.effective_membership_level
        allow_matching_updates = membership_level is not None and membership_level >= OrganizationMembership.Level.ADMIN
        try:
            account = api.update_account_for_view(
                team_id=self.team_id,
                account_id=self.kwargs["pk"],
                input=contracts.UpdateAccountInput(
                    name=data.name if "name" in request.data else None,
                    external_id=data.external_id if "external_id" in request.data else None,
                    external_id_provided="external_id" in request.data,
                    properties=data.properties if "properties" in request.data else None,
                    properties_provided="properties" in request.data,
                    tags=_account_tags_input(serializer),
                    slack_summary_cadence=data.slack_summary_cadence
                    if "slack_summary_cadence" in request.data
                    else None,
                    slack_summary_cadence_provided="slack_summary_cadence" in request.data,
                    churned_at=data.churned_at if "churned_at" in request.data else None,
                    churned_at_provided="churned_at" in request.data,
                ),
                user_access_control=self.user_access_control,
                required_level=_object_required_level(request, write=True),
                organization_id=self.organization.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
                allow_matching_updates=allow_matching_updates,
            )
        except api.Account_DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        except api.AccountPropertiesValidationError as e:
            raise ValidationError({"properties": e.messages})
        except api.AccountConflictError as e:
            raise Conflict(str(e))
        return Response(AccountSerializer(instance=account).data)

    @extend_schema(parameters=[_ACCOUNT_ID_PARAM])
    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    @extend_schema(parameters=[_ACCOUNT_ID_PARAM], responses={200: AccountChannelSummarySerializer(many=True)})
    @action(methods=["GET"], detail=True)
    def summaries(self, request: Request, *args, **kwargs) -> Response:
        if api.get_accessible_account_id(self.team_id, self.kwargs["pk"], self.user_access_control) is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        def fetch(offset: int, limit: int) -> tuple[list[contracts.AccountChannelSummaryView], int]:
            result = api.list_account_channel_summaries(
                self.team_id, self.kwargs["pk"], self.user_access_control, offset=offset, limit=limit
            )
            return result if result is not None else ([], 0)

        return self._paginate_via_facade(request, fetch, AccountChannelSummarySerializer)

    @extend_schema(parameters=[_ACCOUNT_ID_PARAM])
    def destroy(self, request: Request, *args, **kwargs) -> Response:
        try:
            api.delete_account_for_view(
                team_id=self.team_id,
                account_id=self.kwargs["pk"],
                user_access_control=self.user_access_control,
                required_level=_object_required_level(request, write=True),
                organization_id=self.organization.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except api.Account_DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _account_tags_input(serializer) -> list[str] | None:
    """Tags exactly as the client supplied them (raw initial data), so ``None`` (omitted)
    is distinguished from ``[]`` (clear) — matching ``TaggedItemSerializerMixin``."""
    return serializer.initial_data.get("tags")


@extend_schema(
    tags=["customer_analytics"],
    parameters=[
        OpenApiParameter(
            name="account_id",
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.PATH,
            description="UUID of the parent account.",
        ),
    ],
)
class AccountNotebookViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "account"
    serializer_class = AccountNotebookSerializer
    queryset = None
    lookup_field = "short_id"

    ALLOWED_ORDERING = frozenset({"created_at", "-created_at", "created_by", "-created_by"})

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Full-text search across notebook title and content.",
            ),
            OpenApiParameter(
                name="ordering",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["created_at", "-created_at", "created_by", "-created_by"],
                description="Sort by creation date or author. Defaults to '-created_at'.",
            ),
        ],
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        ordering = request.query_params.get("ordering")
        ordering = ordering if ordering in self.ALLOWED_ORDERING else None
        notebooks = api.list_account_notebooks(
            self.team_id,
            self.parents_query_dict["account_id"],
            user_access_control=self.user_access_control,
            search=request.query_params.get("search", "").strip() or None,
            order=ordering,
        )
        if notebooks is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        page = self.paginate_queryset(notebooks)
        if page is not None:
            return self.get_paginated_response(AccountNotebookSerializer(instance=page, many=True).data)
        return Response(AccountNotebookSerializer(instance=notebooks, many=True).data)

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        notebook = api.get_account_notebook(
            self.team_id,
            self.parents_query_dict["account_id"],
            self.kwargs["short_id"],
            user_access_control=self.user_access_control,
        )
        if notebook is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AccountNotebookSerializer(instance=notebook).data)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = AccountNotebookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        notebook = api.create_account_notebook(
            team_id=self.team_id,
            team=self.team,
            account_id=self.parents_query_dict["account_id"],
            input=contracts.CreateAccountNotebookInput(
                title=data.title,
                content=data.content,
                text_content=data.text_content,
                synthesized_content=_synthesize_notebook_content(data.text_content, data.content),
            ),
            user=cast(User, request.user),
            user_access_control=self.user_access_control,
        )
        if notebook is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AccountNotebookSerializer(instance=notebook).data, status=status.HTTP_201_CREATED)

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        deleted = api.delete_account_notebook(
            team_id=self.team_id,
            account_id=self.parents_query_dict["account_id"],
            short_id=self.kwargs["short_id"],
            user_access_control=self.user_access_control,
        )
        if not deleted:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _synthesize_notebook_content(text_content, existing_content):
    """When the caller passed Markdown ``text_content`` but no usable ProseMirror ``content``
    tree, build one from the Markdown. Agents calling the MCP notebook-create tool typically
    send ``text_content`` only (hand-writing ProseMirror is awkward), and NotebookScene only
    renders ``content`` — so without this the result is a blank page. The tiptap helper lives
    in ``ee.hogai`` and stays in the view so it never reaches the facade import path. Returns
    ``None`` when the caller already supplied usable content (or no markdown)."""
    has_usable_content = (
        isinstance(existing_content, dict)
        and existing_content.get("type") == "doc"
        and isinstance(existing_content.get("content"), list)
    )
    if text_content and not has_usable_content:
        return {"type": "doc", "content": markdown_to_tiptap_nodes(text_content) or [{"type": "paragraph"}]}
    return None


# Module-level (not ViewSet static methods) so the ``list[int]`` return annotation resolves to
# the builtin: the ViewSets define a ``list`` method that shadows ``list`` inside the class body.
def _parse_int_ids_param(request: Request, name: str) -> list[int]:
    """Parse a repeated or comma-joined integer-id query param (e.g. ``created_by`` / ``assigned_to``).

    The generated client serializes an array as a single comma-joined value; accept that
    and the repeated-param form alike."""
    ids: list[int] = []
    for value in request.query_params.getlist(name):
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            if not part.isdigit():
                raise ValidationError({name: "Must be a comma-separated list of numeric user IDs."})
            ids.append(int(part))
    return ids


def _parse_uuid_param(request: Request, name: str) -> UUID | None:
    if raw := request.query_params.get(name):
        try:
            return UUID(raw)
        except ValueError:
            raise ValidationError({name: "Must be a valid UUID."})
    return None


@extend_schema(tags=["customer_analytics"])
class AccountNotesViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    _FacadePaginationMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "account"
    serializer_class = AccountNoteSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Full-text search across note title and content, plus substring match on account name.",
            ),
            OpenApiParameter(
                name="account_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Only return notes linked to this account.",
            ),
            OpenApiParameter(
                name="created_by",
                type=OpenApiTypes.INT,
                many=True,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Only return notes created by these user IDs (repeat the param per user).",
            ),
            OpenApiParameter(
                name="assigned_to",
                type=OpenApiTypes.INT,
                many=True,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Only return notes on accounts assigned to these user IDs "
                "(the account's CSM or account executive; repeat the param per user).",
            ),
        ],
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_account_notes_for_view(
                team_id=self.team_id,
                user_access_control=self.user_access_control,
                offset=offset,
                limit=limit,
                search=request.query_params.get("search", "").strip() or None,
                account_id=_parse_uuid_param(request, "account_id"),
                created_by_ids=_parse_int_ids_param(request, "created_by") or None,
                assigned_to_ids=_parse_int_ids_param(request, "assigned_to") or None,
            ),
            AccountNoteSerializer,
        )


@extend_schema(
    tags=["customer_analytics"],
    parameters=[
        OpenApiParameter(
            name="account_id",
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.PATH,
            description="UUID of the parent account.",
        ),
    ],
)
class CustomPropertyValueViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.GenericViewSet):
    scope_object = "account"
    serializer_class = CustomPropertyValueSerializer
    pagination_class = None

    def _accessible_account_id(self) -> str | None:
        """The parent account's id when the caller has object-level access to it, else ``None``
        (mapped to 404). Object-access filtering lives behind the facade — the view imports no models."""
        return api.get_accessible_account_id(
            self.team_id, self.parents_query_dict["account_id"], user_access_control=self.user_access_control
        )

    @extend_schema(responses={200: CustomPropertyValueSerializer(many=True)})
    def list(self, request: Request, *args, **kwargs) -> Response:
        account_id = self._accessible_account_id()
        if account_id is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        values = api.list_active_custom_property_values(self.team_id, account_id)
        return Response(CustomPropertyValueSerializer(values, many=True).data)

    @extend_schema(request=CustomPropertyValueWriteSerializer, responses={201: CustomPropertyValueSerializer})
    def create(self, request: Request, *args, **kwargs) -> Response:
        account_id = self._accessible_account_id()
        if account_id is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        write = CustomPropertyValueWriteSerializer(data=request.data)
        write.is_valid(raise_exception=True)

        try:
            value = api.set_custom_property_value(
                team_id=self.team_id,
                account_id=account_id,
                definition_id=write.validated_data["definition"],
                value=write.validated_data["value"],
                actor=cast(User, request.user),
            )
        except api.Account_DoesNotExist:
            # The account passed the access pre-check but was deleted before the write committed.
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except api.CustomPropertyDefinitionNotFound:
            raise ValidationError({"definition": "Custom property definition not found."})
        except api.CustomPropertyValueSourceManaged as exc:
            raise ValidationError({"definition": str(exc)})
        except api.InvalidCustomPropertyValue as exc:
            raise ValidationError({"value": str(exc)})
        except api.CustomPropertyValueConflict as exc:
            raise Conflict(str(exc))

        return Response(CustomPropertyValueSerializer(value).data, status=status.HTTP_201_CREATED)


class AccountRelationshipDeletePermission(BasePermission):
    message = TeamMemberStrictManagementPermission.message

    def has_permission(self, request: Request, view: Any) -> bool:
        return request.method != "DELETE" or TeamMemberStrictManagementPermission().has_permission(request, view)


@extend_schema(
    tags=["customer_analytics"],
    parameters=[
        OpenApiParameter(
            name="account_id",
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.PATH,
            description="UUID of the parent account.",
        ),
    ],
)
class AccountRelationshipViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.GenericViewSet):
    scope_object = "account"
    serializer_class = AccountRelationshipSerializer
    permission_classes = [AccountRelationshipDeletePermission]
    pagination_class = None

    def _accessible_account_id(self) -> str | None:
        """The parent account's id when the caller has object-level access to it, else ``None``
        (mapped to 404). Object-access filtering lives behind the facade — the view imports no models."""
        return api.get_accessible_account_id(
            self.team_id, self.parents_query_dict["account_id"], user_access_control=self.user_access_control
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "include_history",
                OpenApiTypes.BOOL,
                description="Include ended assignments (the full timeline), not just active ones.",
            )
        ],
        responses={200: AccountRelationshipSerializer(many=True)},
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        account_id = self._accessible_account_id()
        if account_id is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        relationships = api.list_account_relationships(
            team_id=self.team_id,
            account_id=account_id,
            include_history=request.query_params.get("include_history", "").lower() == "true",
        )
        return Response(AccountRelationshipSerializer(relationships, many=True).data)

    @extend_schema(request=AccountRelationshipWriteSerializer, responses={201: AccountRelationshipSerializer})
    def create(self, request: Request, *args, **kwargs) -> Response:
        account_id = self._accessible_account_id()
        if account_id is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        write = AccountRelationshipWriteSerializer(data=request.data)
        write.is_valid(raise_exception=True)
        try:
            relationship = api.assign_account_relationship(
                team_id=self.team_id,
                account_id=account_id,
                definition_id=write.validated_data["definition"],
                user_id=write.validated_data["user"],
                created_by=cast(User, request.user),
            )
        except api.Account_DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except api.AccountRelationshipDefinitionNotFound:
            raise ValidationError({"definition": "Relationship definition not found."})
        except api.AccountRelationshipAssigneeNotInOrganization:
            raise ValidationError({"user": "User is not a member of this organization."})
        return Response(AccountRelationshipSerializer(relationship).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: AccountRelationshipSerializer})
    @action(methods=["POST"], detail=True)
    def end(self, request: Request, *args, **kwargs) -> Response:
        account_id = self._accessible_account_id()
        if account_id is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        relationship = api.end_account_relationship(
            team_id=self.team_id,
            account_id=account_id,
            relationship_id=self.kwargs["pk"],
            actor=cast(User, request.user),
        )
        if relationship is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AccountRelationshipSerializer(relationship).data)

    @extend_schema(request=None, responses={204: None})
    def destroy(self, request: Request, *args, **kwargs) -> Response:
        account_id = api.get_editable_account_id(
            self.team_id, self.parents_query_dict["account_id"], user_access_control=self.user_access_control
        )
        if account_id is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        deleted = api.delete_account_relationship(
            team_id=self.team_id,
            account_id=account_id,
            relationship_id=self.kwargs["pk"],
            actor=cast(User, request.user),
        )
        if not deleted:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


_EVENT_STREAM_ID_PARAM = OpenApiParameter(
    "id",
    OpenApiTypes.STR,
    OpenApiParameter.PATH,
    description="A UUID string identifying this event stream.",
)


class EventStreamTestMessageThrottle(UserRateThrottle):
    """Each test message posts to Slack, so cap the rate per user regardless of auth method."""

    scope = "event_stream_test_message"
    rate = "6/minute"


@extend_schema(tags=["customer_analytics"])
class EventStreamViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """The caller's event stream: a live feed of selected accounts' events posted to a
    Slack channel of their choice. Per-user — each team member owns at most one stream, and
    every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
    destination that is re-provisioned inside the same transaction as every write, so
    config and delivery can't drift apart."""

    scope_object = "account"
    serializer_class = EventStreamSerializer
    pagination_class = None  # at most one stream exists per team (one-to-one) — nothing to paginate
    queryset = None  # data is reached through the facade; declared for router/schema only

    def list(self, request: Request, *args, **kwargs) -> Response:
        streams = api.list_event_streams(self.team_id, user=cast(User, request.user))
        return Response(EventStreamSerializer(instance=streams, many=True).data)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = EventStreamSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = cast(User, request.user)
        try:
            with transaction.atomic():
                stream = api.create_event_stream(
                    team_id=self.team_id,
                    enabled=data.enabled,
                    event_names=data.event_names,
                    slack_integration_id=data.slack_integration,
                    slack_channel_id=data.slack_channel_id,
                    slack_channel_name=data.slack_channel_name,
                    user=user,
                )
                api.sync_event_stream_destination_by_id(team=self.team, stream_id=str(stream.id), user=user)
        except api.EventStreamValidationError as e:
            raise ValidationError(str(e))
        except api.EventStreamConflictError as e:
            raise Conflict(str(e))
        return Response(EventStreamSerializer(instance=stream).data, status=status.HTTP_201_CREATED)

    @extend_schema(parameters=[_EVENT_STREAM_ID_PARAM])
    def update(self, request: Request, *args, **kwargs) -> Response:
        partial = kwargs.pop("partial", False)
        serializer = EventStreamSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        user = cast(User, request.user)
        try:
            with transaction.atomic():
                stream = api.update_event_stream(
                    team_id=self.team_id,
                    stream_id=self.kwargs["pk"],
                    fields=_event_stream_write_fields(serializer.validated_data, request.data),
                    user=user,
                )
                if stream is None:
                    return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
                api.sync_event_stream_destination_by_id(team=self.team, stream_id=str(stream.id), user=user)
        except api.EventStreamValidationError as e:
            raise ValidationError(str(e))
        return Response(EventStreamSerializer(instance=stream).data)

    @extend_schema(parameters=[_EVENT_STREAM_ID_PARAM])
    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    @extend_schema(parameters=[_EVENT_STREAM_ID_PARAM])
    def destroy(self, request: Request, *args, **kwargs) -> Response:
        deleted = api.delete_event_stream(
            team_id=self.team_id, stream_id=self.kwargs["pk"], user=cast(User, request.user)
        )
        if not deleted:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        parameters=[_EVENT_STREAM_ID_PARAM],
        request=EventStreamMemberWriteSerializer,
        responses={200: EventStreamSerializer},
    )
    @action(methods=["POST"], detail=True)
    def add_account(self, request: Request, *args, **kwargs) -> Response:
        return self._set_member(request, included=True)

    @extend_schema(
        parameters=[_EVENT_STREAM_ID_PARAM],
        request=EventStreamMemberWriteSerializer,
        responses={200: EventStreamSerializer},
    )
    @action(methods=["POST"], detail=True)
    def remove_account(self, request: Request, *args, **kwargs) -> Response:
        return self._set_member(request, included=False)

    @extend_schema(
        parameters=[_EVENT_STREAM_ID_PARAM],
        request=None,
        responses={200: EventStreamTestMessageSerializer},
    )
    @action(methods=["POST"], detail=True, throttle_classes=[EventStreamTestMessageThrottle])
    def send_test_message(self, request: Request, *args, **kwargs) -> Response:
        try:
            channel_id = api.send_test_slack_message(
                team_id=self.team_id, stream_id=self.kwargs["pk"], user=cast(User, request.user)
            )
        except contracts.EventStreamTestMessageError as e:
            raise ValidationError(str(e))
        if channel_id is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(EventStreamTestMessageSerializer(instance={"channel_id": channel_id}).data)

    def _set_member(self, request: Request, *, included: bool) -> Response:
        write = EventStreamMemberWriteSerializer(data=request.data)
        write.is_valid(raise_exception=True)
        user = cast(User, request.user)
        try:
            with transaction.atomic():
                stream = api.set_event_stream_member(
                    team_id=self.team_id,
                    stream_id=self.kwargs["pk"],
                    account_id=write.validated_data["account_id"],
                    included=included,
                    user=user,
                    user_access_control=self.user_access_control,
                )
                if stream is None:
                    return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
                api.sync_event_stream_destination_by_id(team=self.team, stream_id=str(stream.id), user=user)
        except api.Account_DoesNotExist:
            raise ValidationError({"account_id": "Account not found for this team."})
        return Response(EventStreamSerializer(instance=stream).data)


# Request field -> model column, for translating a write body into facade update fields.
_EVENT_STREAM_WRITE_FIELDS = {
    "enabled": "enabled",
    "event_names": "event_names",
    "slack_integration": "slack_integration_id",
    "slack_channel_id": "slack_channel_id",
    "slack_channel_name": "slack_channel_name",
}


def _event_stream_write_fields(validated, raw_data: dict) -> dict:
    """The event-stream columns the caller actually sent, so a PATCH that omits a field
    leaves it untouched (the serializer fields carry defaults for create)."""
    return {column: getattr(validated, key) for key, column in _EVENT_STREAM_WRITE_FIELDS.items() if key in raw_data}


class CalendarSyncViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.GenericViewSet):
    """Calendar-sync controls for Customer analytics settings. Sync runs on an hourly
    Temporal schedule; this surface only offers the manual "sync now" escape hatch."""

    scope_object = "account"
    scope_object_read_actions = ["list"]
    # Same gate as IntegrationViewSet: any member can read status, starting a run needs admin.
    permission_classes = [TeamMemberStrictManagementPermission]
    serializer_class = CalendarSyncTriggerSerializer
    pagination_class = None  # a team connects a handful of calendars — nothing to paginate
    queryset = None  # no model — state lives in integration config, reached through the facade

    @extend_schema(responses={200: CalendarSyncStatusSerializer(many=True)})
    def list(self, request: Request, *args, **kwargs) -> Response:
        statuses = api.list_calendar_sync_statuses(self.team_id)
        return Response(CalendarSyncStatusSerializer(instance=statuses, many=True).data)

    @validated_request(
        request_serializer=CalendarSyncTriggerSerializer,
        responses={200: OpenApiResponse(response=CalendarSyncTriggerResponseSerializer)},
        summary="Sync a connected calendar now",
        description="Start a sync run for one connected Google Calendar immediately, outside the hourly schedule.",
    )
    @action(methods=["POST"], detail=False, url_path="sync_now")
    def sync_now(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        result = api.trigger_calendar_sync(self.team_id, request.validated_data["integration_id"])
        if result is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CalendarSyncTriggerResponseSerializer({"status": result}).data)
