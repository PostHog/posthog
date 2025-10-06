from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes
from rest_framework.request import Request
from rest_framework.response import Response

from ee.api.scim.auth import SCIMBearerTokenAuthentication
from ee.api.scim.group import PostHogSCIMGroup
from ee.api.scim.user import PostHogSCIMUser
from posthog.models.organization_domain import OrganizationDomain


@csrf_exempt
@api_view(["GET", "POST"])
@authentication_classes([SCIMBearerTokenAuthentication])
def scim_users_view(request: Request, domain_id: str) -> Response:
    """
    SCIM Users endpoint.
    GET: List all users
    POST: Create a new user
    """
    organization_domain: OrganizationDomain = request.auth

    if request.method == "GET":
        users = PostHogSCIMUser.get_for_organization(organization_domain)
        return Response(
            {
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
                "totalResults": len(users),
                "startIndex": 1,
                "itemsPerPage": len(users),
                "Resources": [user.to_dict() for user in users],
            }
        )

    elif request.method == "POST":
        try:
            scim_user = PostHogSCIMUser.from_dict(request.data, organization_domain)
            return Response(scim_user.to_dict(), status=status.HTTP_201_CREATED)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@csrf_exempt
@api_view(["GET", "PUT", "PATCH", "DELETE"])
@authentication_classes([SCIMBearerTokenAuthentication])
def scim_user_detail_view(request: Request, domain_id: str, user_id: str) -> Response:
    """
    SCIM User detail endpoint.
    GET: Retrieve a user
    PUT: Replace a user
    PATCH: Update a user
    DELETE: Delete a user (remove from org)
    """
    organization_domain: OrganizationDomain = request.auth

    try:
        from posthog.models import User

        user = User.objects.get(id=user_id)
        scim_user = PostHogSCIMUser(user, organization_domain)
    except User.DoesNotExist:
        return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        return Response(scim_user.to_dict())

    elif request.method == "PUT":
        try:
            scim_user = PostHogSCIMUser.from_dict(request.data, organization_domain)
            return Response(scim_user.to_dict())
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == "PATCH":
        try:
            operations = request.data.get("Operations", [])
            for op in operations:
                if op.get("op") == "replace":
                    scim_user.handle_replace(op.get("value", {}))
            return Response(scim_user.to_dict())
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == "DELETE":
        scim_user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@csrf_exempt
@api_view(["GET", "POST"])
@authentication_classes([SCIMBearerTokenAuthentication])
def scim_groups_view(request: Request, domain_id: str) -> Response:
    """
    SCIM Groups endpoint.
    GET: List all groups (roles)
    POST: Create a new group (role)
    """
    organization_domain: OrganizationDomain = request.auth

    if request.method == "GET":
        groups = PostHogSCIMGroup.get_for_organization(organization_domain)
        return Response(
            {
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
                "totalResults": len(groups),
                "startIndex": 1,
                "itemsPerPage": len(groups),
                "Resources": [group.to_dict() for group in groups],
            }
        )

    elif request.method == "POST":
        try:
            scim_group = PostHogSCIMGroup.from_dict(request.data, organization_domain)
            return Response(scim_group.to_dict(), status=status.HTTP_201_CREATED)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@csrf_exempt
@api_view(["GET", "PUT", "PATCH", "DELETE"])
@authentication_classes([SCIMBearerTokenAuthentication])
def scim_group_detail_view(request: Request, domain_id: str, group_id: str) -> Response:
    """
    SCIM Group detail endpoint.
    GET: Retrieve a group
    PUT: Replace a group
    PATCH: Update a group
    DELETE: Delete a group
    """
    organization_domain: OrganizationDomain = request.auth

    try:
        from ee.models.rbac.role import Role

        role = Role.objects.get(id=group_id, organization=organization_domain.organization)
        scim_group = PostHogSCIMGroup(role, organization_domain)
    except Role.DoesNotExist:
        return Response({"detail": "Group not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        return Response(scim_group.to_dict())

    elif request.method == "PUT":
        try:
            scim_group = PostHogSCIMGroup.from_dict(request.data, organization_domain)
            return Response(scim_group.to_dict())
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == "PATCH":
        try:
            operations = request.data.get("Operations", [])
            for op in operations:
                if op.get("op") == "replace":
                    scim_group.handle_replace(op.get("value", {}))
            return Response(scim_group.to_dict())
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == "DELETE":
        scim_group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@csrf_exempt
@api_view(["GET"])
@authentication_classes([SCIMBearerTokenAuthentication])
def scim_service_provider_config_view(request: Request, domain_id: str) -> Response:
    """
    SCIM Service Provider Configuration endpoint.
    Returns capabilities of this SCIM implementation.
    """
    return Response(
        {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
            "documentationUri": "https://posthog.com/docs/scim",
            "patch": {"supported": True},
            "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
            "filter": {"supported": False, "maxResults": 0},
            "changePassword": {"supported": False},
            "sort": {"supported": False},
            "etag": {"supported": False},
            "authenticationSchemes": [
                {
                    "type": "oauthbearertoken",
                    "name": "OAuth Bearer Token",
                    "description": "Authentication scheme using the OAuth Bearer Token Standard",
                    "specUri": "https://www.rfc-editor.org/rfc/rfc6750.txt",
                    "documentationUri": "https://posthog.com/docs/scim",
                }
            ],
        }
    )


@csrf_exempt
@api_view(["GET"])
@authentication_classes([SCIMBearerTokenAuthentication])
def scim_resource_types_view(request: Request, domain_id: str) -> Response:
    """
    SCIM Resource Types endpoint.
    """
    return Response(
        {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
            "totalResults": 2,
            "Resources": [
                PostHogSCIMUser.resource_type_dict(request),
                PostHogSCIMGroup.resource_type_dict(request),
            ],
        }
    )


@csrf_exempt
@api_view(["GET"])
@authentication_classes([SCIMBearerTokenAuthentication])
def scim_schemas_view(request: Request, domain_id: str) -> Response:
    """
    SCIM Schemas endpoint.
    """
    from django_scim import constants

    return Response(
        {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
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
