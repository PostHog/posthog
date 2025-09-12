import base64
from typing import cast

from django.conf import settings

import requests
import structlog
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.models import User
from posthog.utils import capture_exception

logger = structlog.get_logger(__name__)


def get_zendesk_auth_headers():
    email = settings.ZENDESK_ADMIN_EMAIL
    token = settings.ZENDESK_API_TOKEN

    if not email or not token:
        raise ValueError("ZENDESK_ADMIN_EMAIL and ZENDESK_API_TOKEN must be set")

    basic_token = base64.b64encode(f"{email}/token:{token}".encode("ascii")).decode("ascii")
    return {"Authorization": f"Basic {basic_token}"}


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ensure_zendesk_organization(request: Request) -> Response:
    try:
        data = request.data
        org_id = data.get("organization_id")
        org_name = data.get("organization_name")
        user = cast(User, request.user)

        # Validate that the user can only submit for their own organization
        if user.current_organization_id and str(org_id) != str(user.current_organization_id):
            capture_exception(
                Exception("User attempted to create Zendesk organization for different organization"),
                {
                    "user_org_id": user.current_organization_id,
                    "requested_org_id": org_id,
                    "user_email": user.email,
                },
            )
            return Response({"status": "success"})

        if not org_id or not org_name:
            capture_exception(
                Exception("Missing organization_id or organization_name in Zendesk org creation request"),
                {
                    "org_id": org_id,
                    "org_name": org_name,
                    "user_email": user.email,
                },
            )
            return Response({"status": "success"})

        subdomain = settings.ZENDESK_SUBDOMAIN
        if not subdomain:
            capture_exception(
                Exception("ZENDESK_SUBDOMAIN not configured for Zendesk org creation"),
                {
                    "org_id": org_id,
                    "org_name": org_name,
                    "user_email": user.email,
                },
            )
            return Response({"status": "success"})

        base_url = f"https://{subdomain}.zendesk.com/api/v2"
        auth_headers = get_zendesk_auth_headers()

        search_url = f"{base_url}/organizations/search.json"
        search_params = {"external_id": org_id}

        search_response = requests.get(search_url, headers=auth_headers, params=search_params, timeout=10)

        if search_response.status_code == 200:
            search_data = search_response.json()
            organizations = search_data.get("organizations", [])
            if organizations and len(organizations) > 0:
                return Response({"status": "success"})

        create_url = f"{base_url}/organizations.json"
        create_payload = {
            "organization": {
                "name": org_name,
                "external_id": org_id,
                "organization_fields": {"ph_external_id_org": org_id},
            }
        }

        requests.post(
            create_url, headers={**auth_headers, "Content-Type": "application/json"}, json=create_payload, timeout=10
        )

        return Response({"status": "success"})

    except Exception as e:
        capture_exception(
            e,
            {
                "org_id": org_id,
                "org_name": org_name,
                "user_email": user.email,
            },
        )
        logger.warning(
            "ZenDesk organization creation failed",
            error=str(e),
            org_id=org_id,
        )
        return Response({"status": "success"})
