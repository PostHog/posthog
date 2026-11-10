from datetime import timedelta

from django.conf import settings

from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

# The player gets one token when it lists a recording's sources, then fetches fonts through the proxy
# for as long as someone watches. The export rasterizer also reuses one token for a whole render.
REPLAY_PROXY_TOKEN_TTL = timedelta(hours=1)

REPLAY_PROXY_JWT_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.REPLAY_PROXY,
    settings_name="REPLAY_PROXY_JWT_SECRET",
    default_ttl=REPLAY_PROXY_TOKEN_TTL,
)


def mint_replay_proxy_token(team_id: int) -> str | None:
    if not REPLAY_PROXY_JWT_PURPOSE.enabled():
        return None
    # One proxy serves US and EU, whose team ids overlap, so the proxy logs the region next to the team id.
    return REPLAY_PROXY_JWT_PURPOSE.mint({"team_id": team_id, "region": settings.CLOUD_DEPLOYMENT})
