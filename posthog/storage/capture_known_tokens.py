"""Redis projection of every live project API token, read by capture at the edge.

Capture validates only the shape of a token, so an event sent with a token that
belongs to no team is accepted with a 200 and dropped much later in ingestion. The
sender sees nothing. This projection gives capture an authoritative negative: a
token absent from it, while the sweep marker is fresh, belongs to no team.

The contract is deliberately fail-open. Capture accepts the event whenever it
cannot tell -- a missing or stale sweep marker, a Redis error, a timeout -- so a
paused sweep or a Redis outage never rejects good traffic.

Two kinds of write keep the projection current:

* the `post_save` receiver on `Team`, so a project created a second ago is already
  known and its first event is never refused;
* the periodic sweep, which rebuilds the whole projection and refreshes the marker.
"""

from collections.abc import Iterable, Iterator

from django.utils import timezone

import structlog
from redis import RedisError

from posthog.redis import get_client
from posthog.settings import PLUGINS_RELOAD_REDIS_URL

logger = structlog.get_logger(__name__)

KNOWN_TOKEN_KEY_PREFIX = "capture_known_token"
SWEEP_MARKER_KEY = "capture_known_tokens_swept_at"

# An entry outlives several sweeps, so one skipped sweep cannot thin the projection
# out. The marker, not the entry TTL, is what capture trusts for freshness.
KNOWN_TOKEN_TTL_SECONDS = 14 * 24 * 60 * 60
SWEEP_MARKER_TTL_SECONDS = 24 * 60 * 60

WRITE_BATCH_SIZE = 1000


def token_key(token: str) -> str:
    return f"{KNOWN_TOKEN_KEY_PREFIX}:{token}"


def _client():
    return get_client(PLUGINS_RELOAD_REDIS_URL)


def _batched(tokens: Iterable[str], size: int) -> Iterator[list[str]]:
    batch: list[str] = []
    for token in tokens:
        if token:
            batch.append(token)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def mark_tokens_known(tokens: Iterable[str]) -> int:
    """Record tokens as belonging to a team. Returns how many entries were written."""

    client = _client()
    written = 0
    for batch in _batched(tokens, WRITE_BATCH_SIZE):
        pipeline = client.pipeline(transaction=False)
        for token in batch:
            pipeline.setex(token_key(token), KNOWN_TOKEN_TTL_SECONDS, "1")
        pipeline.execute()
        written += len(batch)
    return written


def forget_token(token: str) -> None:
    """Drop a token from the projection, for a deleted team."""

    if not token:
        return
    _client().delete(token_key(token))


def record_sweep_completed() -> None:
    """Publish the freshness marker capture gates every rejection on."""

    _client().setex(SWEEP_MARKER_KEY, SWEEP_MARKER_TTL_SECONDS, str(int(timezone.now().timestamp())))


def sweep_known_tokens() -> int:
    """Rebuild the projection from the database and refresh the freshness marker.

    Entries for tokens that no longer exist are left to expire rather than deleted:
    over-accepting for at most one TTL is the safe direction, and scanning Redis for
    strays would cost more than it saves.
    """

    from posthog.models.team.team import Team

    tokens = Team.objects.values_list("api_token", flat=True).iterator(chunk_size=WRITE_BATCH_SIZE)
    written = mark_tokens_known(tokens)
    record_sweep_completed()
    logger.info("capture_known_tokens.sweep_completed", tokens=written)
    return written


def mark_team_token_known(token: str) -> None:
    """Best-effort single-token write for the `Team` save path.

    A Redis failure here must never fail a team save. The next sweep picks the token
    up, and until then capture fails open for it.
    """

    if not token:
        return
    try:
        mark_tokens_known([token])
    except RedisError:
        logger.warning("capture_known_tokens.mark_failed", exc_info=True)


def forget_team_token(token: str) -> None:
    """Best-effort single-token delete for the `Team` delete path."""

    try:
        forget_token(token)
    except RedisError:
        logger.warning("capture_known_tokens.forget_failed", exc_info=True)
