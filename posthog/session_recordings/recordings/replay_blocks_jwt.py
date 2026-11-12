import time
from datetime import UTC, datetime, timedelta
from typing import Literal

from django.conf import settings

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

# recording-api refuses a token older than 2 hours. One hour leaves room for clock skew, and the player gets a new
# token each time it lists sources.
REPLAY_BLOCKS_TOKEN_TTL = timedelta(hours=1)

REPLAY_BLOCKS_JWT_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.REPLAY_BLOCKS,
    settings_name="RECORDING_API_BLOCKS_JWT_SECRET",
    default_ttl=REPLAY_BLOCKS_TOKEN_TTL,
)

REPLAY_DIRECT_BLOCKS_FLAG = "replay-direct-blocks"


def is_direct_blocks_enabled(team_id: int) -> bool:
    """Gate for giving the player block urls. The player polls the listing for a live recording, so the check sends
    no flag-called event."""
    # Team ids repeat across deployments, so a team condition also names the deployment. A condition on the distinct id
    # cannot be evaluated locally, so team_id is sent as a property for team targeting.
    person_properties: dict[str, str | int] = {"team_id": team_id}
    if settings.CLOUD_DEPLOYMENT:
        person_properties["cloud_deployment"] = settings.CLOUD_DEPLOYMENT
    try:
        return bool(
            posthoganalytics.feature_enabled(
                REPLAY_DIRECT_BLOCKS_FLAG,
                str(team_id),
                person_properties=person_properties,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False


# recording-api gives the browser tier a budget per viewer and the API tiers one budget per team.
ReplayBlocksTier = Literal["browser", "free", "paid", "enterprise"]


@frozen
class ReplayBlocksToken:
    token: str
    expires_at: datetime


def mint_replay_blocks_token(
    team_id: int, session_id: str, viewer: str, tier: ReplayBlocksTier
) -> ReplayBlocksToken | None:
    """A token that reads the blocks of one session. `viewer` is also a segment of every block URL, so the browser
    keeps a separate cache entry for each viewer. Returns None until the signing key is provisioned."""
    if not REPLAY_BLOCKS_JWT_PURPOSE.enabled():
        return None
    now = int(time.time())
    expires_at = datetime.fromtimestamp(now, tz=UTC) + REPLAY_BLOCKS_TOKEN_TTL
    token = REPLAY_BLOCKS_JWT_PURPOSE.mint(
        # recording-api checks the token's age against iat, which encode_jwt does not set.
        {"team_id": team_id, "session_id": session_id, "sub": viewer, "tier": tier, "iat": now},
        ttl=REPLAY_BLOCKS_TOKEN_TTL,
    )
    return ReplayBlocksToken(token=token, expires_at=expires_at)
