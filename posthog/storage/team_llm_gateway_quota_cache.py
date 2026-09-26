"""
Per-team quota blob that the Go ai-gateway's credit-bucket gate reads.

Only a team limited on an AI credit bucket or in a deactivated org has a blob. The gateway reads
absence as open, so lifting a limit deletes the key. Keyed by team id because the gateway knows
the billed team only as an id.
"""

import os
import json
import time
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from itertools import batched
from typing import Any, NamedTuple

from django.conf import settings
from django.db.models import Q, QuerySet
from django.db.models.functions import Coalesce

import structlog

from posthog.caching.ai_gateway_redis_cache import AI_GATEWAY_DEDICATED_CACHE_ALIAS
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType

logger = structlog.get_logger(__name__)

# Strings so this module does not import the billing package at load time; a test pins them to QuotaResource.
AI_CREDITS_BUCKET = "ai_credits"
POSTHOG_CODE_CREDITS_BUCKET = "posthog_code_credits"
AI_GATEWAY_QUOTA_BUCKETS: tuple[str, ...] = (AI_CREDITS_BUCKET, POSTHOG_CODE_CREDITS_BUCKET)

LLM_GATEWAY_QUOTA_VERSION = 1

# Margin past the limit's end so the blob outlives the zset score it mirrors.
LLM_GATEWAY_QUOTA_TTL_MARGIN_SECONDS = int(os.environ.get("LLM_GATEWAY_QUOTA_TTL_MARGIN_SECONDS", "300"))
# A deactivated org has no period end, so the reconcile re-stamps its blobs.
LLM_GATEWAY_QUOTA_DEACTIVATED_TTL = int(os.environ.get("LLM_GATEWAY_QUOTA_DEACTIVATED_TTL", str(30 * 24 * 60 * 60)))

LLM_GATEWAY_QUOTA_CACHE_EXPIRY_SORTED_SET = "llm_gateway_quota_cache_expiry"
LLM_GATEWAY_QUOTA_RESTAMP_WINDOW_SECONDS = 7 * 24 * 60 * 60
_MAX_PROJECTION_WRITES = 3
_BATCH_SIZE = 500


def _never_load(team_key: KeyType) -> dict[str, Any] | HyperCacheStoreMissing:
    # Write-only from Django, but HyperCache requires a loader. The gateway reads a miss sentinel as open.
    return HyperCacheStoreMissing()


team_llm_gateway_quota_hypercache = HyperCache(
    namespace="team_metadata",
    value="llm_gateway_quota.json",
    token_based=False,
    load_fn=_never_load,
    cache_ttl=LLM_GATEWAY_QUOTA_DEACTIVATED_TTL,
    cache_miss_ttl=60 * 60 * 24,
    cache_alias=(AI_GATEWAY_DEDICATED_CACHE_ALIAS if AI_GATEWAY_DEDICATED_CACHE_ALIAS in settings.CACHES else None),
    s3_enabled=False,
    expiry_sorted_set_key=LLM_GATEWAY_QUOTA_CACHE_EXPIRY_SORTED_SET,
)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


def build_quota_blob(
    team_id: int, limited_until: Mapping[str, float], org_active: bool, now: datetime
) -> dict[str, Any] | None:
    now_ts = now.timestamp()
    buckets: dict[str, dict[str, Any]] = {}
    if not org_active:
        for bucket in AI_GATEWAY_QUOTA_BUCKETS:
            buckets[bucket] = {"limited": True, "limited_until": None}
    else:
        for bucket in AI_GATEWAY_QUOTA_BUCKETS:
            until = limited_until.get(bucket)
            if until is not None and until >= now_ts:
                buckets[bucket] = {"limited": True, "limited_until": _iso(until)}
    if not buckets:
        return None
    return {
        "team_id": team_id,
        "version": LLM_GATEWAY_QUOTA_VERSION,
        "buckets": buckets,
        "org_deactivated": not org_active,
        "projected_at": now.isoformat(),
    }


def quota_blob_ttl(blob: Mapping[str, Any], now: datetime) -> int:
    if blob.get("org_deactivated"):
        return LLM_GATEWAY_QUOTA_DEACTIVATED_TTL
    latest = 0.0
    for state in blob["buckets"].values():
        until = state.get("limited_until")
        if until:
            latest = max(latest, datetime.fromisoformat(until).timestamp())
    return max(1, int(latest - now.timestamp()) + LLM_GATEWAY_QUOTA_TTL_MARGIN_SECONDS)


def _enabled() -> bool:
    return bool(settings.AI_GATEWAY_REDIS_URL)


def deactivated_teams_needing_a_blob() -> QuerySet[Team]:
    """Teams of deactivated orgs that can still spend at the gateway: tokens minted within the
    deactivated window are live, or the team has a standing gateway credential."""
    from posthog.models.project_secret_api_key import ProjectSecretAPIKey  # noqa: PLC0415
    from posthog.storage.gateway_credential_cache import GATEWAY_CREDENTIAL_REQUIRED_SCOPE  # noqa: PLC0415

    recent = datetime.now(tz=UTC) - timedelta(seconds=LLM_GATEWAY_QUOTA_DEACTIVATED_TTL)
    # A secret key bills its project root, so the root is the team that needs the blob.
    key_roots = (
        ProjectSecretAPIKey.objects.filter(scopes__contains=[GATEWAY_CREDENTIAL_REQUIRED_SCOPE])
        .annotate(root_team_id=Coalesce("team__parent_team_id", "team_id"))
        .values("root_team_id")
    )
    return (
        Team.objects.filter(organization__is_active=False)
        .filter(
            Q(organization__updated_at__gte=recent)
            | Q(llm_gateway_enabled_at__isnull=False, llm_gateway_revoked_at__isnull=True)
            | Q(id__in=key_roots)
            | Q(organization__oauth_applications__isnull=False)
        )
        .distinct()
    )


def _derive_blobs(teams: list[Team], now: datetime) -> dict[int, dict[str, Any] | None]:
    from ee.billing.quota_limiting import get_teams_limited_until  # noqa: PLC0415

    # A NULL is_active counts as active.
    active_by_org = dict(
        Organization.objects.filter(id__in={team.organization_id for team in teams}).values_list("id", "is_active")
    )
    active = {team.id: active_by_org.get(team.organization_id) is not False for team in teams}
    inactive_ids = [team.id for team in teams if not active[team.id]]
    reachable = (
        set(deactivated_teams_needing_a_blob().filter(id__in=inactive_ids).values_list("id", flat=True))
        if inactive_ids
        else set()
    )
    limited = get_teams_limited_until([team.api_token for team in teams if active[team.id]], AI_GATEWAY_QUOTA_BUCKETS)
    blobs: dict[int, dict[str, Any] | None] = {}
    for team in teams:
        if active[team.id]:
            blobs[team.id] = build_quota_blob(team.id, limited[team.api_token], True, now)
        else:
            blobs[team.id] = build_quota_blob(team.id, {}, False, now) if team.id in reachable else None
    return blobs


@frozen
class _BlobState:
    org_deactivated: Any
    buckets: Any


def _blob_state(blob: Mapping[str, Any] | None) -> _BlobState | None:
    return None if blob is None else _BlobState(org_deactivated=blob["org_deactivated"], buckets=blob["buckets"])


def _write_blob(team: Team, blob: dict[str, Any] | None, now: datetime) -> None:
    if blob is None:
        team_llm_gateway_quota_hypercache.delete_cache_entry(team, kinds=["redis"])
    else:
        team_llm_gateway_quota_hypercache.set_cache_value_redis_only(
            team, blob, ttl=quota_blob_ttl(blob, now), track_expiry=True
        )


def _capture_failure(message: str, error: Exception, **fields: Any) -> None:
    logger.warning(message, error_type=type(error).__name__, error=str(error), **fields)
    capture_exception(error)


def _derive_or_capture(teams: list[Team], now: datetime) -> dict[int, dict[str, Any] | None]:
    """Empty when the read fails. No per-team input fails alone, so a failure means a store is
    down: capture it once and leave the batch to the reconcile."""
    if not teams:
        return {}
    try:
        return _derive_blobs(teams, now)
    except Exception as e:
        _capture_failure("llm_gateway_quota: projection read failed", e, teams=len(teams))
        return {}


class _Projected(NamedTuple):
    written: int
    cleared: int


def _project_batch(teams: list[Team]) -> _Projected:
    """Writes each blob, then re-reads and rewrites what moved. Writers race, and each re-read
    follows every earlier write, so the last write carries current state. Failures are captured
    for the reconcile, never raised into billing. Counts the blobs left written and the clears
    that succeeded."""
    by_id = {team.id: team for team in teams}
    written: dict[int, dict[str, Any] | None] = {}
    to_write = _derive_or_capture(teams, datetime.now(tz=UTC))
    for _ in range(_MAX_PROJECTION_WRITES):
        now = datetime.now(tz=UTC)
        for team_id, blob in to_write.items():
            try:
                _write_blob(by_id[team_id], blob, now)
                written[team_id] = blob
            except Exception as e:
                _capture_failure("llm_gateway_quota: projection write failed", e, team_id=team_id)
                written.pop(team_id, None)
        current = _derive_or_capture([by_id[team_id] for team_id in written], datetime.now(tz=UTC))
        to_write = {
            team_id: current[team_id]
            for team_id in written
            if team_id in current and _blob_state(current[team_id]) != _blob_state(written[team_id])
        }
        if not to_write:
            break
    else:
        # State kept moving; the reconcile re-projects these teams within a tick.
        logger.warning("llm_gateway_quota: projection did not settle", team_ids=sorted(to_write))
    blobs = sum(1 for blob in written.values() if blob is not None)
    return _Projected(blobs, len(written) - blobs)


def _project_in_batches(queryset: QuerySet[Team]) -> _Projected:
    written = cleared = 0
    for batch in batched(queryset.iterator(chunk_size=_BATCH_SIZE), _BATCH_SIZE, strict=False):
        projected = _project_batch(list(batch))
        written += projected.written
        cleared += projected.cleared
    return _Projected(written, cleared)


def _project_teams(queryset: QuerySet[Team]) -> _Projected:
    return _project_in_batches(queryset.only("id", "api_token", "organization_id"))


def project_team_quota(team: Team) -> bool | None:
    """True when a blob is written, False when cleared, None when the projection failed or is off."""
    if not _enabled():
        return None
    projected = _project_batch([team])
    return True if projected.written else False if projected.cleared else None


def clear_team_quota(team: Team | int) -> None:
    if not _enabled():
        return
    try:
        team_llm_gateway_quota_hypercache.delete_cache_entry(team, kinds=["redis"])
    except Exception as e:
        team_id = team.id if isinstance(team, Team) else team
        logger.warning("llm_gateway_quota: clear failed", team_id=team_id, error=str(e))
        capture_exception(e)


def project_org_quota(organization: Organization) -> int:
    """Includes child environments so an obo naming either the project or an environment resolves."""
    if not _enabled():
        return 0
    return _project_teams(organization.teams.all()).written


def project_teams_quota_by_token(tokens: Iterable[str]) -> int:
    if not _enabled():
        return 0
    token_list = [t for t in set(tokens) if t]
    if not token_list:
        return 0
    return _project_teams(Team.objects.filter(api_token__in=token_list)).written


def projected_team_ids(expiring_before: float | None = None) -> set[int]:
    if not _enabled():
        return set()
    client = get_client(team_llm_gateway_quota_hypercache.redis_url)
    if expiring_before is None:
        members = client.zrange(LLM_GATEWAY_QUOTA_CACHE_EXPIRY_SORTED_SET, 0, -1)
    else:
        members = client.zrangebyscore(LLM_GATEWAY_QUOTA_CACHE_EXPIRY_SORTED_SET, "-inf", f"({expiring_before}")
    out: set[int] = set()
    for member in members:
        raw = member.decode("utf-8") if isinstance(member, bytes) else str(member)
        try:
            out.add(int(raw))
        except ValueError:
            continue
    return out


def _untrack(team_ids: set[int], *, expired_before: float) -> None:
    if not team_ids:
        return
    client = get_client(team_llm_gateway_quota_hypercache.redis_url)
    expired = projected_team_ids(expiring_before=expired_before) & team_ids
    if expired:
        client.zrem(LLM_GATEWAY_QUOTA_CACHE_EXPIRY_SORTED_SET, *(str(team_id) for team_id in expired))


# django_redis writes KEY_PREFIX:VERSION:key; the gateway derives the same prefix.
_DJANGO_REDIS_KEY_PREFIX = "posthog:1:"


def _missing_blobs(team_ids: set[int]) -> set[int]:
    missing: set[int] = set()
    ordered = sorted(team_ids)
    client = team_llm_gateway_quota_hypercache.cache_client
    for start in range(0, len(ordered), 500):
        keys = {
            team_llm_gateway_quota_hypercache.get_cache_key(team_id): team_id
            for team_id in ordered[start : start + 500]
        }
        present = client.get_many(list(keys))
        missing.update(team_id for key, team_id in keys.items() if key not in present)
    return missing


def reconcile_quota_projection() -> dict[str, int]:
    """Re-projects every team limited on an AI bucket or in a reachable deactivated org, and every
    team with a blob, which deletes a stray one."""
    if not _enabled():
        return {"candidates": 0, "written": 0, "cleared": 0, "failed": 0}
    from ee.billing.quota_limiting import (  # noqa: PLC0415
        QuotaLimitingCaches,
        QuotaResource,
        list_team_attributes_in_zset,
    )

    tokens: set[str] = set()
    for bucket in AI_GATEWAY_QUOTA_BUCKETS:
        tokens.update(list_team_attributes_in_zset(QuotaResource(bucket), QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY))
    now_ts = time.time()
    have = projected_team_ids()
    expiring = projected_team_ids(expiring_before=now_ts + LLM_GATEWAY_QUOTA_RESTAMP_WINDOW_SECONDS)
    have_active = dict(Team.objects.filter(id__in=have).values_list("id", "organization__is_active"))
    # A deleted team is never re-projected; drop its tracking once its blob has expired.
    _untrack(have - set(have_active), expired_before=now_ts)
    deactivated_have = {team_id for team_id, active in have_active.items() if active is False}
    # Only deactivated teams that can still spend keep a blob. A present one is left until its
    # window, so the tick does not rewrite every deactivated team; one that can no longer spend
    # is re-projected once, which deletes it.
    reachable = set(deactivated_teams_needing_a_blob().values_list("id", flat=True))
    ids = (
        expiring
        | (set(have_active) - deactivated_have)
        | (deactivated_have - reachable)
        | _missing_blobs(reachable - expiring)
    )
    candidates = Team.objects.filter(Q(api_token__in=tokens) | Q(id__in=ids))
    total = candidates.count()
    projected = _project_teams(candidates)
    failed = max(0, total - projected.written - projected.cleared)
    return {"candidates": total, "written": projected.written, "cleared": projected.cleared, "failed": failed}


def get_team_quota_blob(team: Team | int) -> dict[str, Any] | None:
    """Redis-only read that never fills the cache. The cache holds the JSON text the gateway decodes."""
    value = team_llm_gateway_quota_hypercache.cache_client.get(team_llm_gateway_quota_hypercache.get_cache_key(team))
    if isinstance(value, dict):
        return value
    if isinstance(value, str | bytes):
        try:
            decoded = json.loads(value)
        except ValueError:
            return None
        return decoded if isinstance(decoded, dict) else None
    return None


def quota_blob_ttl_remaining(team: Team | int) -> int | None:
    client = get_client(team_llm_gateway_quota_hypercache.redis_url)
    ttl = client.ttl(_DJANGO_REDIS_KEY_PREFIX + team_llm_gateway_quota_hypercache.get_cache_key(team))
    return None if ttl is None or ttl < 0 else int(ttl)
