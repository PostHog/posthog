import base64
import structlog
import requests
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

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

        if not org_id or not org_name:
            return Response({"status": "success"})

        subdomain = settings.ZENDESK_SUBDOMAIN
        if not subdomain:
            return Response({"status": "success"})

        base_url = f"https://{subdomain}.zendesk.com/api/v2"
        auth_headers = get_zendesk_auth_headers()

        search_url = f"{base_url}/organizations/search.json"
        search_params = {"external_id": org_id}

        search_response = requests.get(search_url, headers=auth_headers, params=search_params, timeout=10)

        if search_response.status_code == 200:
            search_data = search_response.json()
            if search_data.get("organizations") and len(search_data["organizations"]) > 0:
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
        logger.warning(
            "ZenDesk organization creation failed",
            error=str(e),
            org_id=data.get("organization_id") if "data" in locals() else None,
        )
        return Response({"status": "success"})
