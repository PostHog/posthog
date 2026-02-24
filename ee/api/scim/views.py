from typing import Any, cast

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
from posthog.models.organization_domain import OrganizationDomain

from ee.api.scim.auth import SCIMBearerTokenAuthentication
from ee.api.scim.group import PostHogSCIMGroup
from ee.api.scim.user import PostHogSCIMUser, SCIMUserConflict
from ee.api.scim.utils import detect_identity_provider, mask_scim_filter, mask_scim_payload, normalize_scim_operations
from ee.models.rbac.role import Role
from ee.models.scim_provisioned_user import SCIMProvisionedUser

logger = structlog.get_logger(__name__)

SCIM_DEFAULT_START_INDEX = 1
SCIM_MAX_RESULTS = 200

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

    @staticmethod
    def _get_validation_error_detail(detail: Any) -> str:
        if isinstance(detail, list):
            return str(detail[0]) if detail else "Invalid request"
        if isinstance(detail, dict):
            if not detail:
                return "Invalid request"
            first_value = next(iter(detail.values()))
            if isinstance(first_value, list):
                return str(first_value[0]) if first_value else "Invalid request"
            return str(first_value)
        return str(detail)

    def get_pagination_params(self, request: Request) -> tuple[int, int | None]:
        start_index_param = request.query_params.get("startIndex")
        count_param = request.query_params.get("count")

        if start_index_param is None:
            start_index = SCIM_DEFAULT_START_INDEX
        else:
            try:
                start_index = int(start_index_param)
            except ValueError as error:
                raise drf_exceptions.ValidationError("startIndex must be an integer") from error
            if start_index < SCIM_DEFAULT_START_INDEX:
                raise drf_exceptions.ValidationError("startIndex must be greater than or equal to 1")

        if count_param is None:
            return start_index, None

        try:
            count = int(count_param)
        except ValueError as error:
            raise drf_exceptions.ValidationError("count must be an integer") from error

        if count < 0:
            raise drf_exceptions.ValidationError("count must be greater than or equal to 0")

        return start_index, min(count, SCIM_MAX_RESULTS)

    @staticmethod
    def paginate_queryset(queryset: QuerySet, start_index: int, count: int | None) -> QuerySet:
        offset = start_index - 1
        if count is None:
            return queryset[offset:]
        return queryset[offset : offset + count]

    @staticmethod
    def build_list_response(resources: list[dict[str, Any]], total_results: int, start_index: int) -> Response:
        return Response(
            {
                "schemas": [constants.SchemaURI.LIST_RESPONSE],
                "totalResults": total_results,
                "startIndex": start_index,
                "itemsPerPage": len(resources),
                "Resources": resources,
            }
        )

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)

        drf_request = self.request
        log_data: dict = {
            "method": drf_request.method,
            "path": drf_request.path,
            "idp": detect_identity_provider(drf_request).value,
            "response_status": response.status_code,
        }

        if drf_request.auth:
            organization_domain = cast(OrganizationDomain, drf_request.auth)
            log_data["organization_domain"] = organization_domain.domain

        if drf_request.method in ("POST", "PUT", "PATCH"):
            payload = drf_request.data
            if payload is not None:
                log_data["payload"] = mask_scim_payload(payload)
        filter_param = drf_request.GET.get("filter")
        if filter_param:
            log_data["filter"] = mask_scim_filter(filter_param)

        logger.info("scim_request", **log_data)

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
        if isinstance(exc, drf_exceptions.ValidationError):
            detail = self._get_validation_error_detail(exc.detail)
            return Response(
                {
                    "schemas": [constants.SchemaURI.ERROR],
                    "status": 400,
                    "detail": detail,
                },
                status=status.HTTP_400_BAD_REQUEST,
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
            return User.objects.filter(id__in=scim_user_ids)

        raw_queryset = super().search(filter_query, request)
        user_ids = [user.id for user in raw_queryset]
        return User.objects.filter(
            id__in=user_ids,
            organization_membership__organization=org_domain.organization,
        )


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
        )


class SCIMUsersView(SCIMBaseView):
    def get(self, request: Request, domain_id: str) -> Response:
        organization_domain = cast(OrganizationDomain, request.auth)
        filter_param = request.query_params.get("filter")
        start_index, count = self.get_pagination_params(request)

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
            queryset = User.objects.filter(
                organization_membership__organization=organization_domain.organization,
            )

        queryset = queryset.order_by("id").distinct()
        total_results = queryset.count()
        paginated_queryset = self.paginate_queryset(queryset, start_index, count)
        users = [PostHogSCIMUser(user, organization_domain) for user in paginated_queryset]
        return self.build_list_response(
            resources=[user.to_dict() for user in users],
            total_results=total_results,
            start_index=start_index,
        )

    def post(self, request: Request, domain_id: str) -> Response:
        organization_domain = cast(OrganizationDomain, request.auth)

        try:
            identity_provider = detect_identity_provider(request)
            scim_user = PostHogSCIMUser.from_dict(request.data, organization_domain, identity_provider)
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
        try:
            scim_user.put(request.data)
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
        try:
            operations = request.data.get("Operations", [])
            operations = normalize_scim_operations(operations)
            scim_user.handle_operations(operations)
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
        scim_user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SCIMGroupsView(SCIMBaseView):
    def get(self, request: Request, domain_id: str) -> Response:
        organization_domain = cast(OrganizationDomain, request.auth)
        filter_param = request.query_params.get("filter")
        start_index, count = self.get_pagination_params(request)

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
            queryset = Role.objects.filter(organization=organization_domain.organization)

        queryset = queryset.order_by("id").distinct()
        total_results = queryset.count()
        paginated_queryset = self.paginate_queryset(queryset, start_index, count)
        groups = [PostHogSCIMGroup(role, organization_domain) for role in paginated_queryset]
        return self.build_list_response(
            resources=[group.to_dict() for group in groups],
            total_results=total_results,
            start_index=start_index,
        )

    def post(self, request: Request, domain_id: str) -> Response:
        organization_domain = cast(OrganizationDomain, request.auth)
        try:
            scim_group = PostHogSCIMGroup.from_dict(request.data, organization_domain)
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
                "filter": {"supported": True, "maxResults": SCIM_MAX_RESULTS},
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
