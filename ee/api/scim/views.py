import time
import dataclasses
from typing import cast

from django.db.models import Q, QuerySet

import structlog
from django_scim import constants
from django_scim.filters import GroupFilterQuery, UserFilterQuery
from rest_framework import (
    exceptions as drf_exceptions,
    status,
)
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from scim2_filter_parser.transpilers.django_q_object import get_query

from posthog.exceptions_capture import capture_exception
from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, log_activity
from posthog.models.organization_domain import OrganizationDomain

from ee.api.scim.auth import SCIMBearerTokenAuthentication
from ee.api.scim.group import PostHogSCIMGroup
from ee.api.scim.user import PostHogSCIMUser, SCIMUserConflict
from ee.api.scim.utils import (
    detect_identity_provider,
    mask_headers,
    mask_scim_filter,
    mask_scim_payload,
    normalize_scim_operations,
)
from ee.models.rbac.role import Role
from ee.models.scim_provisioned_user import SCIMProvisionedUser
from ee.models.scim_request_log import SCIMRequestLog

logger = structlog.get_logger(__name__)

MAX_ITEMS_PER_PAGE = 200


class SCIMPaginationError(Exception):
    """Raised when SCIM pagination query parameters are invalid"""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _parse_scim_pagination(request: Request) -> tuple[int, int]:
    """Parse startIndex and count from SCIM query params.

    Returns (start_index, count) following django-scim2 conventions.
    Raises SCIMPaginationError for invalid values.
    """
    try:
        start_index = int(request.query_params.get("startIndex", 1))
    except (ValueError, TypeError):
        raise SCIMPaginationError("Invalid startIndex value")

    try:
        count = int(request.query_params.get("count", MAX_ITEMS_PER_PAGE))
    except (ValueError, TypeError):
        raise SCIMPaginationError("Invalid count value")

    if start_index < 1:
        raise SCIMPaginationError("Invalid startIndex (must be >= 1)")

    if count < 0:
        raise SCIMPaginationError("Invalid count (must be >= 0)")

    count = min(count, MAX_ITEMS_PER_PAGE)
    return start_index, count


def _build_scim_list_response(
    queryset: QuerySet,
    start_index: int,
    count: int,
    adapter_cls: type[PostHogSCIMUser] | type[PostHogSCIMGroup],
    organization_domain: "OrganizationDomain",
) -> dict:
    total_results = queryset.count()

    if count == 0:
        resources: list[dict] = []
    else:
        offset = start_index - 1
        page = queryset[offset : offset + count]
        resources = [adapter_cls(obj, organization_domain).to_dict() for obj in page]

    return {
        "schemas": [constants.SchemaURI.LIST_RESPONSE],
        "totalResults": total_results,
        "startIndex": start_index,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


@dataclasses.dataclass(frozen=True)
class SCIMContext(ActivityContextBase):
    identity_provider: str = ""
    organization_domain: str = ""
    scim_username: str = ""


def _log_scim_activity(
    *,
    organization_domain: OrganizationDomain,
    activity: str,
    user_id: str,
    user_email: str,
    request: Request,
) -> None:
    idp = detect_identity_provider(request)
    log_activity(
        organization_id=organization_domain.organization_id,
        team_id=None,
        user=None,
        was_impersonated=False,
        item_id=user_id,
        scope="User",
        activity=activity,
        detail=Detail(
            name=user_email,
            context=SCIMContext(
                identity_provider=idp.value,
                organization_domain=organization_domain.domain,
                scim_username=request.data.get("userName", ""),
            ),
        ),
    )


def _log_scim_group_activity(
    *,
    organization_domain: OrganizationDomain,
    activity: str,
    role: Role,
    request: Request,
) -> None:
    idp = detect_identity_provider(request)
    log_activity(
        organization_id=organization_domain.organization_id,
        team_id=None,
        user=None,
        was_impersonated=False,
        item_id=str(role.id),
        scope="Role",
        activity=activity,
        detail=Detail(
            name=role.name,
            context=SCIMContext(
                identity_provider=idp.value,
                organization_domain=organization_domain.domain,
            ),
        ),
    )


SCIM_USER_ATTR_MAP = {
    ("emails", "value", None): "email",
    ("name", "familyName", None): "last_name",
    ("familyName", None, None): "last_name",
    ("name", "givenName", None): "first_name",
    ("givenName", None, None): "first_name",
    ("active", None, None): "is_active",
}

SCIM_GROUP_ATTR_MAP = {
    ("displayName", None, None): "name",
}


class SCIMJSONParser(JSONParser):
    media_type = "application/scim+json"


class SCIMJSONRenderer(JSONRenderer):
    media_type = "application/scim+json"


class SCIMBaseView(APIView):
    """
    Base view for all SCIM endpoints.
    """

    authentication_classes = [SCIMBearerTokenAuthentication]
    renderer_classes = [SCIMJSONRenderer, JSONRenderer]
    parser_classes = [SCIMJSONParser, JSONParser]

    def dispatch(self, request, *args, **kwargs):
        start = time.monotonic()
        response = super().dispatch(request, *args, **kwargs)
        duration_ms = int((time.monotonic() - start) * 1000)

        drf_request = self.request
        idp = detect_identity_provider(drf_request).value

        log_data: dict = {
            "method": drf_request.method,
            "path": drf_request.get_full_path(),
            "idp": idp,
            "response_status": response.status_code,
        }

        organization_domain = None
        if drf_request.auth:
            organization_domain = cast(OrganizationDomain, drf_request.auth)
            log_data["organization_domain"] = organization_domain.domain

        masked_body = None
        if drf_request.method in ("POST", "PUT", "PATCH"):
            payload = drf_request.data
            if payload is not None:
                masked_body = mask_scim_payload(payload)
                log_data["payload"] = masked_body

        filter_param = drf_request.GET.get("filter")
        if filter_param:
            log_data["filter"] = mask_scim_filter(filter_param)

        logger.info("scim_request", **log_data)

        if organization_domain is not None:
            try:
                SCIMRequestLog.objects.create(
                    organization_domain=organization_domain,
                    request_method=drf_request.method or "",
                    request_path=drf_request.get_full_path(),
                    request_headers=mask_headers(dict(drf_request.headers)),
                    request_body=masked_body,
                    response_status=response.status_code,
                    response_body=response.data if hasattr(response, "data") else None,
                    identity_provider=idp,
                    duration_ms=duration_ms,
                )
            except Exception:
                logger.exception("scim_request_log_save_failed")

        return response

    def handle_exception(self, exc):
        if isinstance(exc, drf_exceptions.NotAuthenticated):
            return Response(
                {
                    "schemas": [constants.SchemaURI.ERROR],
                    "status": 401,
                    "detail": "No bearer token provided",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if isinstance(exc, drf_exceptions.AuthenticationFailed):
            return Response(
                {
                    "schemas": [constants.SchemaURI.ERROR],
                    "status": 403,
                    "detail": "Authentication failed",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().handle_exception(exc)


class PostHogUserFilterQuery(UserFilterQuery):
    attr_map = SCIM_USER_ATTR_MAP

    @classmethod
    def search(cls, filter_query: str, request: Request) -> QuerySet[User]:
        org_domain = cast(OrganizationDomain, request.auth)

        if "userName" in filter_query:
            # userName is stored in SCIMProvisionedUser, not User
            # UserFilterQuery only queries User model, so use scim2-filter-parser directly
            scim_attr_map = {("userName", None, None): "username"}
            q_obj = get_query(filter_query, scim_attr_map)
            scim_user_ids = SCIMProvisionedUser.objects.filter(
                q_obj,
                organization_domain=org_domain,
            ).values_list("user_id", flat=True)
            return User.objects.filter(id__in=scim_user_ids).order_by("id")

        raw_queryset = super().search(filter_query, request)
        user_ids = [user.id for user in raw_queryset]
        return User.objects.filter(
            id__in=user_ids,
            organization_membership__organization=org_domain.organization,
        ).order_by("id")


class PostHogGroupFilterQuery(GroupFilterQuery):
    attr_map = SCIM_GROUP_ATTR_MAP

    @classmethod
    def search(cls, filter_query: str, request: Request) -> QuerySet[Role]:
        raw_queryset = super().search(filter_query, request)
        # Filter results to only include roles from the specified organization
        org_domain = cast(OrganizationDomain, request.auth)
        role_ids = [role.id for role in raw_queryset]
        return Role.objects.filter(
            id__in=role_ids,
            organization=org_domain.organization,
        ).order_by("id")


class SCIMUsersView(SCIMBaseView):
    def get(self, request: Request, domain_id: str) -> Response:
        organization_domain = cast(OrganizationDomain, request.auth)
        filter_param = request.query_params.get("filter")

        try:
            start_index, count = _parse_scim_pagination(request)
        except SCIMPaginationError as e:
            return Response(
                {"schemas": [constants.SchemaURI.ERROR], "status": 400, "detail": e.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if filter_param:
            try:
                queryset = PostHogUserFilterQuery.search(filter_param, request)
            except Exception as e:
                capture_exception(
                    e,
                    additional_properties={
                        "scim_operation": "filter_users",
                        "filter": filter_param,
                        "domain_id": domain_id,
                        "organization_id": organization_domain.organization.id,
                    },
                )
                queryset = User.objects.none()
        else:
            queryset = PostHogSCIMUser.get_queryset_for_organization(organization_domain)

        return Response(_build_scim_list_response(queryset, start_index, count, PostHogSCIMUser, organization_domain))

    def post(self, request: Request, domain_id: str) -> Response:
        organization_domain = cast(OrganizationDomain, request.auth)

        try:
            identity_provider = detect_identity_provider(request)
            scim_user = PostHogSCIMUser.from_dict(request.data, organization_domain, identity_provider)
            _log_scim_activity(
                organization_domain=organization_domain,
                activity="scim_provisioned",
                user_id=scim_user.id,
                user_email=scim_user.obj.email,
                request=request,
            )
            return Response(scim_user.to_dict(), status=status.HTTP_201_CREATED)
        except SCIMUserConflict:
            return Response(
                {"schemas": [constants.SchemaURI.ERROR], "status": 409, "detail": "User already exists"},
                status=status.HTTP_409_CONFLICT,
            )
        except ValueError as e:
            capture_exception(
                e,
                additional_properties={
                    "scim_operation": "create_user",
                    "domain_id": domain_id,
                    "organization_id": organization_domain.organization.id,
                    "request_data": request.data,
                },
            )
            return Response(
                {"schemas": [constants.SchemaURI.ERROR], "status": 400, "detail": "Invalid user data"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class SCIMUserDetailView(SCIMBaseView):
    def get_object(self, user_id: int) -> PostHogSCIMUser:
        organization_domain = cast(OrganizationDomain, self.request.auth)
        user = User.objects.filter(
            Q(organization_membership__organization=organization_domain.organization)
            | Q(scim_provisions__organization_domain=organization_domain),
            id=user_id,
        ).first()
        if not user:
            raise User.DoesNotExist()
        return PostHogSCIMUser(user, organization_domain)

    def handle_exception(self, exc):
        if isinstance(exc, User.DoesNotExist):
            return Response(
                {"schemas": [constants.SchemaURI.ERROR], "status": 404, "detail": "User not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return super().handle_exception(exc)

    def get(self, request: Request, domain_id: str, user_id: int) -> Response:
        scim_user = self.get_object(user_id)
        return Response(scim_user.to_dict())

    def put(self, request: Request, domain_id: str, user_id: int) -> Response:
        scim_user = self.get_object(user_id)
        organization_domain = cast(OrganizationDomain, request.auth)
        try:
            scim_user.put(request.data)
            _log_scim_activity(
                organization_domain=organization_domain,
                activity="scim_replaced",
                user_id=str(user_id),
                user_email=scim_user.obj.email,
                request=request,
            )
            return Response(scim_user.to_dict())
        except ValueError as e:
            capture_exception(
                e,
                additional_properties={
                    "scim_operation": "replace_user",
                    "user_id": user_id,
                    "domain_id": domain_id,
                    "organization_id": cast(OrganizationDomain, request.auth).organization.id,
                    "request_data": request.data,
                },
            )
            return Response(
                {"schemas": [constants.SchemaURI.ERROR], "status": 400, "detail": "Invalid user data"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def patch(self, request: Request, domain_id: str, user_id: int) -> Response:
        scim_user = self.get_object(user_id)
        organization_domain = cast(OrganizationDomain, request.auth)
        try:
            operations = request.data.get("Operations", [])
            operations = normalize_scim_operations(operations)
            scim_user.handle_operations(operations)
            _log_scim_activity(
                organization_domain=organization_domain,
                activity="scim_updated",
                user_id=str(user_id),
                user_email=scim_user.obj.email,
                request=request,
            )
            return Response(scim_user.to_dict())
        except Exception as e:
            capture_exception(
                e,
                additional_properties={
                    "scim_operation": "update_user",
                    "user_id": user_id,
                    "domain_id": domain_id,
                    "organization_id": cast(OrganizationDomain, request.auth).organization.id,
                    "request_data": request.data,
                },
            )
            return Response(
                {"schemas": [constants.SchemaURI.ERROR], "status": 400, "detail": "Failed to update user"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def delete(self, request: Request, domain_id: str, user_id: int) -> Response:
        scim_user = self.get_object(user_id)
        user_email = scim_user.obj.email
        scim_user.delete()
        organization_domain = cast(OrganizationDomain, request.auth)
        _log_scim_activity(
            organization_domain=organization_domain,
            activity="scim_deprovisioned",
            user_id=str(user_id),
            user_email=user_email,
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class SCIMGroupsView(SCIMBaseView):
    def get(self, request: Request, domain_id: str) -> Response:
        organization_domain = cast(OrganizationDomain, request.auth)
        filter_param = request.query_params.get("filter")

        try:
            start_index, count = _parse_scim_pagination(request)
        except SCIMPaginationError as e:
            return Response(
                {"schemas": [constants.SchemaURI.ERROR], "status": 400, "detail": e.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if filter_param:
            try:
                queryset = PostHogGroupFilterQuery.search(filter_param, request)
            except Exception as e:
                capture_exception(
                    e,
                    additional_properties={
                        "scim_operation": "filter_groups",
                        "filter": filter_param,
                        "domain_id": domain_id,
                        "organization_id": organization_domain.organization.id,
                    },
                )
                queryset = Role.objects.none()
        else:
            queryset = PostHogSCIMGroup.get_queryset_for_organization(organization_domain)

        return Response(_build_scim_list_response(queryset, start_index, count, PostHogSCIMGroup, organization_domain))

    def post(self, request: Request, domain_id: str) -> Response:
        organization_domain = cast(OrganizationDomain, request.auth)
        try:
            scim_group = PostHogSCIMGroup.from_dict(request.data, organization_domain)
            _log_scim_group_activity(
                organization_domain=organization_domain,
                activity="scim_provisioned",
                role=scim_group.obj,
                request=request,
            )
            return Response(scim_group.to_dict(), status=status.HTTP_201_CREATED)
        except ValueError as e:
            capture_exception(
                e,
                additional_properties={
                    "scim_operation": "create_group",
                    "domain_id": domain_id,
                    "organization_id": organization_domain.organization.id,
                    "request_data": request.data,
                },
            )
            return Response(
                {"schemas": [constants.SchemaURI.ERROR], "status": 400, "detail": "Invalid group data"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class SCIMGroupDetailView(SCIMBaseView):
    def get_object(self, group_id: str) -> PostHogSCIMGroup:
        organization_domain = cast(OrganizationDomain, self.request.auth)
        role = Role.objects.filter(id=group_id, organization=organization_domain.organization).first()
        if not role:
            raise Role.DoesNotExist()
        return PostHogSCIMGroup(role, organization_domain)

    def handle_exception(self, exc):
        if isinstance(exc, Role.DoesNotExist):
            return Response(
                {"schemas": [constants.SchemaURI.ERROR], "status": 404, "detail": "Group not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return super().handle_exception(exc)

    def get(self, request: Request, domain_id: str, group_id: str) -> Response:
        scim_group = self.get_object(group_id)
        return Response(scim_group.to_dict())

    def put(self, request: Request, domain_id: str, group_id: str) -> Response:
        scim_group = self.get_object(group_id)
        try:
            scim_group.put(request.data)
            _log_scim_group_activity(
                organization_domain=cast(OrganizationDomain, request.auth),
                activity="scim_replaced",
                role=scim_group.obj,
                request=request,
            )
            return Response(scim_group.to_dict())
        except ValueError as e:
            capture_exception(
                e,
                additional_properties={
                    "scim_operation": "replace_group",
                    "group_id": group_id,
                    "domain_id": domain_id,
                    "organization_id": cast(OrganizationDomain, request.auth).organization.id,
                    "request_data": request.data,
                },
            )
            return Response(
                {"schemas": [constants.SchemaURI.ERROR], "status": 400, "detail": "Invalid group data"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def patch(self, request: Request, domain_id: str, group_id: str) -> Response:
        scim_group = self.get_object(group_id)
        try:
            operations = request.data.get("Operations", [])
            scim_group.handle_operations(operations)
            _log_scim_group_activity(
                organization_domain=cast(OrganizationDomain, request.auth),
                activity="scim_updated",
                role=scim_group.obj,
                request=request,
            )
            return Response(scim_group.to_dict())
        except Exception as e:
            capture_exception(
                e,
                additional_properties={
                    "scim_operation": "update_group",
                    "group_id": group_id,
                    "domain_id": domain_id,
                    "organization_id": cast(OrganizationDomain, request.auth).organization.id,
                    "request_data": request.data,
                },
            )
            return Response(
                {"schemas": [constants.SchemaURI.ERROR], "status": 400, "detail": "Failed to update group"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def delete(self, request: Request, domain_id: str, group_id: str) -> Response:
        scim_group = self.get_object(group_id)
        organization_domain = cast(OrganizationDomain, request.auth)
        # Log before delete: Role.delete() runs inside a transaction, which causes
        # log_activity to defer via on_commit. The outer test transaction never commits,
        # but more importantly the role row is gone by the time on_commit fires in prod.
        _log_scim_group_activity(
            organization_domain=organization_domain,
            activity="scim_deprovisioned",
            role=scim_group.obj,
            request=request,
        )
        scim_group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SCIMServiceProviderConfigView(SCIMBaseView):
    def get(self, request: Request, domain_id: str) -> Response:
        return Response(
            {
                "schemas": [constants.SchemaURI.SERVICE_PROVIDER_CONFIG],
                "documentationUri": "https://posthog.com/docs/scim",
                "patch": {"supported": True},
                "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
                "filter": {"supported": True, "maxResults": MAX_ITEMS_PER_PAGE},
                "changePassword": {"supported": False},
                "sort": {"supported": False},
                "etag": {"supported": False},
                "authenticationSchemes": [
                    {
                        "type": "oauthbearertoken",
                        "name": "OAuth Bearer Token",
                        "description": "Authentication scheme using the OAuth Bearer Token Standard",
                        "specUri": "https://www.rfc-editor.org/rfc/rfc6750.txt",
                        "documentationUri": "https://posthog.com/docs/settings/scim",
                    }
                ],
            }
        )


class SCIMResourceTypesView(SCIMBaseView):
    def get(self, request: Request, domain_id: str) -> Response:
        return Response(
            {
                "schemas": [constants.SchemaURI.LIST_RESPONSE],
                "totalResults": 2,
                "Resources": [
                    PostHogSCIMUser.resource_type_dict(request),
                    PostHogSCIMGroup.resource_type_dict(request),
                ],
            }
        )


class SCIMSchemasView(SCIMBaseView):
    def get(self, request: Request, domain_id: str) -> Response:
        return Response(
            {
                "schemas": [constants.SchemaURI.LIST_RESPONSE],
                "totalResults": 2,
                "Resources": [
                    {
                        "id": constants.SchemaURI.USER,
                        "name": "User",
                        "description": "User Account",
                    },
                    {
                        "id": constants.SchemaURI.GROUP,
                        "name": "Group",
                        "description": "Group",
                    },
                ],
            }
        )
