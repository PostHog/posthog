from django.conf import settings
from django.http import JsonResponse
from django.views import View

DEFINITIONS_METADATA_PATH = "api/oauth/posthog-definitions/client-metadata"


class DefinitionsClientMetadataView(View):
    """
    Serves a static CIMD (Client ID Metadata Document) for the posthog-definitions
    CLI — infrastructure-as-code for PostHog dashboards and insights.

    The client_id in the response is the canonical URL where this document is hosted,
    constructed from SITE_URL so it's correct on each region (US, EU, self-hosted).

    redirect_uris is registered as the portless localhost form (`http://localhost/callback`)
    so the loopback port-flexibility logic in OAuthValidator.validate_redirect_uri accepts
    any ephemeral callback port the CLI chooses at runtime.
    """

    http_method_names = ["get"]

    def get(self, request):
        client_id = f"{settings.SITE_URL}/{DEFINITIONS_METADATA_PATH}"

        metadata = {
            "client_id": client_id,
            "client_name": "posthog-definitions",
            "redirect_uris": ["http://localhost/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }

        response = JsonResponse(metadata)
        response["Cache-Control"] = "public, max-age=3600"
        response["Content-Type"] = "application/json"
        return response
