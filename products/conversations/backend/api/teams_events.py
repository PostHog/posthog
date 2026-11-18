"""Microsoft Teams Bot Framework messaging endpoint for SupportHog."""

from posthog.ingress.teams.provider import build_teams_provider
from posthog.ingress.views import build_webhook_view

from products.conversations.backend.support_teams import (
    get_botframework_issuers,
    get_botframework_jwks_uri,
    get_teams_app_id,
)

teams_event_handler = build_webhook_view(
    build_teams_provider(
        jwks_uri_getter=get_botframework_jwks_uri,
        audience_getter=get_teams_app_id,
        issuers_getter=get_botframework_issuers,
    )
)
