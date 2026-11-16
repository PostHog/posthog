from typing import cast

from django.conf import settings
from django.core.management.base import BaseCommand

from posthog.api.oauth.cimd import CIMDMetadataDocument, _create_cimd_application
from posthog.models import OAuthApplication

# The client metadata documents PostHog publishes from PostHog/posthog.com
# (static/.well-known/oauth/<app>/client-metadata.json). A local stack can't count on reaching
# posthog.com, so the seed creates each app from this copy. The first real use refreshes it from
# the published document.
POSTHOG_CIMD_DOCUMENTS: list[dict[str, object]] = [
    {
        "client_id": "https://posthog.com/.well-known/oauth/hog/client-metadata.json",
        "client_name": "hog CLI for PostHog",
        "logo_uri": "https://posthog.com/.well-known/oauth/hog/logo.png",
        "grant_types": ["urn:ietf:params:oauth:grant-type:device_code", "refresh_token"],
        "token_endpoint_auth_method": "none",
    },
    {
        "client_id": "https://posthog.com/.well-known/oauth/hogli/client-metadata.json",
        "client_name": "hogli CLI for PostHog",
        "logo_uri": "https://posthog.com/.well-known/oauth/hogli/logo.png",
        "redirect_uris": ["http://127.0.0.1/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "com.posthog": {"scopes": ["engineering_analytics:read"]},
    },
    {
        "client_id": "https://posthog.com/.well-known/oauth/webmcp/client-metadata.json",
        "client_name": "PostHog WebMCP",
        "logo_uri": "https://posthog.com/.well-known/oauth/webmcp/logo.png",
        "redirect_uris": ["https://us.posthog.com/webmcp/callback", "https://eu.posthog.com/webmcp/callback"],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    },
    {
        "client_id": "https://posthog.com/.well-known/oauth/visual-review/client-metadata.json",
        "client_name": "PostHog Visual Review for GitHub",
        "client_uri": "https://github.com/PostHog/visual-review-extension",
        "logo_uri": "https://posthog.com/.well-known/oauth/visual-review/logo.png",
        "redirect_uris": ["https://coegljbgaffjilmoampifafjigkdmjaf.chromiumapp.org/"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "com.posthog": {"scopes": ["visual_review:read", "user:read", "project:read", "organization:read"]},
    },
    {
        "client_id": "https://posthog.com/.well-known/oauth/desktop-announcements-admin/client-metadata.json",
        "client_name": "PostHog Desktop Announcements Admin",
        "client_uri": "https://desktop-announcements-admin.hosthog.dev/",
        "logo_uri": "https://posthog.com/.well-known/oauth/desktop-announcements-admin/logo.png",
        "redirect_uris": ["https://desktop-announcements-admin.hosthog.dev/oauth/callback"],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "com.posthog": {"scopes": ["feature_flag:read", "feature_flag:write", "user:read"]},
    },
]


class Command(BaseCommand):
    help = "Create PostHog's own CIMD client applications, verified, for a local stack"

    def handle(self, *args, **options):
        # Verifying an app is a staff decision everywhere else, so only a local stack does it here.
        site_url = settings.SITE_URL or ""
        if (
            not settings.DEBUG
            or settings.CLOUD_DEPLOYMENT
            or not ("//localhost" in site_url or "//127.0.0.1" in site_url)
        ):
            self.stdout.write("Skipping PostHog CIMD app setup; it only runs on a local stack")
            return

        for document in POSTHOG_CIMD_DOCUMENTS:
            client_id = str(document["client_id"])
            app = OAuthApplication.objects.filter(client_id=client_id).first()
            if app is None:
                app = _create_cimd_application(
                    client_id, cast(CIMDMetadataDocument, document), capture_ph_event=lambda **_: None
                )
                self.stdout.write(self.style.SUCCESS(f"Created CIMD app '{app.name}' ({client_id})"))
            # A device client works only while it is verified, and staff verify PostHog's own apps.
            if not app.is_verified:
                app.is_verified = True
                app.save(update_fields=["is_verified"])
                self.stdout.write(self.style.SUCCESS(f"Verified CIMD app '{app.name}'"))
