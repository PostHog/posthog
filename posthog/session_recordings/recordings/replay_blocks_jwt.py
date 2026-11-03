import time
from datetime import UTC, datetime, timedelta
from typing import Literal

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
    try:
        return bool(
            posthoganalytics.feature_enabled(REPLAY_DIRECT_BLOCKS_FLAG, str(team_id), send_feature_flag_events=False)
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
    team_id: int, session_id: str, viewer: str, tier: ReplayBlocksTier, not_after: datetime | None = None
) -> ReplayBlocksToken | None:
    """A token that reads the blocks of one session. `viewer` is also a segment of every block URL, so the browser
    keeps a separate cache entry for each viewer. `not_after` caps the lifetime, so a token never outlives the access
    that granted it. Returns None until the signing key is provisioned, or when that access already ended."""
    if not REPLAY_BLOCKS_JWT_PURPOSE.enabled():
        return None
    now = int(time.time())
    issued_at = datetime.fromtimestamp(now, tz=UTC)
    expires_at = issued_at + REPLAY_BLOCKS_TOKEN_TTL
    if not_after is not None:
        expires_at = min(expires_at, not_after)
    if expires_at <= datetime.now(tz=UTC):
        return None
    token = REPLAY_BLOCKS_JWT_PURPOSE.mint(
        # recording-api checks the token's age against iat, which encode_jwt does not set.
        {"team_id": team_id, "session_id": session_id, "sub": viewer, "tier": tier, "iat": now},
        ttl=expires_at - issued_at,
    )
    return ReplayBlocksToken(token=token, expires_at=expires_at)
