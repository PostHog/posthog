from django.conf import settings
from django.http import JsonResponse
from django.views import View

RAYCAST_METADATA_PATH = "api/oauth/raycast/client-metadata"

# Scope ceiling for tokens issued to the Raycast extension. OIDC scopes
# (openid/profile/email) bypass the ceiling via ALWAYS_ALLOWED_SCOPES.
RAYCAST_SCOPES = [
    "project:read",
    "feature_flag:read",
    "cohort:read",
    "dashboard:read",
    "person:read",
    "insight:read",
    "query:read",
    "user:read",
]


class RaycastClientMetadataView(View):
    """
    Serves a static CIMD (Client ID Metadata Document) for the PostHog Raycast extension.

    The client_id in the response is the canonical URL where this document is hosted,
    constructed from SITE_URL so it's correct on each region (US, EU, self-hosted).
    """

    http_method_names = ["get"]

    def get(self, request):
        client_id = f"{settings.SITE_URL}/{RAYCAST_METADATA_PATH}"

        metadata = {
            "client_id": client_id,
            "client_name": "Raycast extension for PostHog",
            "redirect_uris": [
                "https://raycast.com/redirect?packageName=Extension",
                "https://raycast.com/redirect?packageName=posthog",
            ],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "com.posthog": {"scopes": RAYCAST_SCOPES},
        }

        response = JsonResponse(metadata)
        response["Cache-Control"] = "public, max-age=3600"
        response["Content-Type"] = "application/json"
        return response
