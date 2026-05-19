from django.conf import settings
from django.http import JsonResponse
from django.views import View

WIZARD_METADATA_PATH = "api/oauth/wizard/client-metadata"


class WizardClientMetadataView(View):
    """
    Serves a static CIMD (Client ID Metadata Document) for the PostHog Wizard CLI.

    The client_id in the response is the canonical URL where this document is hosted,
    constructed from SITE_URL so it's correct on each region (US, EU, self-hosted).
    """

    http_method_names = ["get"]

    def get(self, request):
        client_id = f"{settings.SITE_URL}/{WIZARD_METADATA_PATH}"

        metadata = {
            "client_id": client_id,
            "client_name": "PostHog Wizard",
            "redirect_uris": ["http://localhost:8239/callback"],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }

        response = JsonResponse(metadata)
        response["Cache-Control"] = "public, max-age=3600"
        response["Content-Type"] = "application/json"
        return response
