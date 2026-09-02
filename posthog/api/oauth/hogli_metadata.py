from django.conf import settings
from django.http import JsonResponse
from django.views import View

HOGLI_METADATA_PATH = "api/oauth/hogli/client-metadata"

# Scope ceiling: /authorize clamps to this, so keep it to what a hogli command actually reads.
HOGLI_SCOPES = [
    "engineering_analytics:read",
]

# Tracked on `main` rather than pinned to a commit: a moved file only hides the image, while a
# pin would keep serving stale art through a rebrand.
HOGLI_LOGO_URI = "https://raw.githubusercontent.com/PostHog/brand/main/assets/crests/full/png/dev-experience.png"


class HogliClientMetadataView(View):
    """
    Serves a static CIMD (Client ID Metadata Document) for the hogli CLI.

    The client_id in the response is the canonical URL where this document is hosted,
    constructed from SITE_URL so it's correct on each region (US, EU, self-hosted).

    The redirect is registered without a port because RFC 8252 section 7.3 obliges the server
    to accept any port on a loopback address, which lets each login bind a free ephemeral port
    against this one entry.
    """

    http_method_names = ["get"]

    def get(self, request):
        client_id = f"{settings.SITE_URL}/{HOGLI_METADATA_PATH}"

        metadata = {
            "client_id": client_id,
            "client_name": "hogli CLI for PostHog",
            "logo_uri": HOGLI_LOGO_URI,
            "redirect_uris": ["http://127.0.0.1/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "com.posthog": {"scopes": HOGLI_SCOPES},
        }

        response = JsonResponse(metadata)
        response["Cache-Control"] = "public, max-age=3600"
        response["Content-Type"] = "application/json"
        return response
