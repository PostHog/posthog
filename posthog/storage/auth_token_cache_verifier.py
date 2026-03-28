"""
Periodic verification for the per-token auth cache.

Scans all `posthog:auth_token:*` keys in Redis, deserializes the cached
TokenAuthData, and verifies each entry against the database. Deletes stale
entries that signal-based invalidation may have missed.

Unlike HyperCache verification (which iterates teams and checks their cache),
this iterates Redis keys and reverse-lookups in the DB — because the auth cache
is keyed by token hash, not by team ID.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import redis as redis_lib
import structlog
from prometheus_client import Counter

from posthog.exceptions_capture import capture_exception
from posthog.metrics import TOMBSTONE_COUNTER
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.storage.team_access_cache import TOKEN_CACHE_PREFIX

# Number of characters to log from a cache key (prefix + 8 chars of hash for correlation)
_LOG_KEY_PREFIX_LEN = len(TOKEN_CACHE_PREFIX) + 8

logger = structlog.get_logger(__name__)

AUTH_TOKEN_VERIFY_ERRORS_COUNTER = Counter(
    "posthog_auth_token_verify_errors_total",
    "Errors during auth token cache verification",
)


@dataclass
class AuthTokenVerificationResult:
    total_scanned: int = 0
    valid: int = 0
    stale_found: int = 0
    delete_errors: int = 0
    parse_errors: int = 0
    db_errors: int = 0
    stale_by_type: dict[str, int] = field(
        default_factory=lambda: {
            "secret": 0,
            "personal": 0,
            "project_secret": 0,
            "unknown": 0,
        }
    )


def verify_and_fix_auth_token_cache(
    redis_client: redis_lib.Redis,
    batch_size: int = 200,
    scan_count: int = 500,
    soft_limit_seconds: float = 19 * 60,
) -> AuthTokenVerificationResult:
    """Scan all auth token cache entries and delete stale ones.

    Uses cursor-based SCAN (non-blocking) to iterate keys, MGET for batch
    reads, and batch DB queries to verify entries efficiently.

    Stops early (with a warning log) if ``soft_limit_seconds`` elapses so
    the caller's Celery soft time limit doesn't interrupt mid-batch silently.
    """
    import time

    result = AuthTokenVerificationResult()

    scan_pattern = f"{TOKEN_CACHE_PREFIX}*"
    batch: list[str] = []
    start = time.monotonic()

    for key in redis_client.scan_iter(match=scan_pattern, count=scan_count):
        if time.monotonic() - start > soft_limit_seconds:
            logger.warning(
                "Auth token verification stopping early: time budget exhausted",
                total_scanned=result.total_scanned,
            )
            break

        key_str = key.decode("utf-8") if isinstance(key, bytes) else key
        batch.append(key_str)

        if len(batch) >= batch_size:
            _verify_batch(redis_client, batch, result)
            batch = []

    if batch:
        _verify_batch(redis_client, batch, result)

    return result


def _verify_batch(
    redis_client: redis_lib.Redis,
    keys: list[str],
    result: AuthTokenVerificationResult,
) -> None:
    """Verify a batch of cache keys against the database."""
    values = redis_client.mget(keys)

    # Parse and group entries by type
    secret_entries: list[tuple[str, dict]] = []
    personal_entries: list[tuple[str, dict]] = []
    project_secret_entries: list[tuple[str, dict]] = []
    stale_keys: list[str] = []

    for key, raw_value in zip(keys, values):
        result.total_scanned += 1
        # Note: keys that expire between SCAN and MGET (raw_value is None) are
        # counted in total_scanned but not in valid/stale/parse counters, so
        # total_scanned >= valid + stale_found + parse_errors is expected.

        if raw_value is None:
            # Key expired or was deleted between SCAN and MGET
            continue

        try:
            value_str = raw_value.decode("utf-8") if isinstance(raw_value, bytes) else raw_value
            data = json.loads(value_str)
        except (json.JSONDecodeError, UnicodeDecodeError):
            result.parse_errors += 1
            stale_keys.append(key)
            _record_stale("unknown", result)
            logger.warning("Malformed auth token cache entry", cache_key=key[:_LOG_KEY_PREFIX_LEN])
            continue

        if not isinstance(data, dict):
            result.parse_errors += 1
            stale_keys.append(key)
            _record_stale("unknown", result)
            logger.warning("Malformed auth token cache entry", cache_key=key[:_LOG_KEY_PREFIX_LEN])
            continue

        token_type = data.get("type")
        if token_type == "secret":
            secret_entries.append((key, data))
        elif token_type == "personal":
            personal_entries.append((key, data))
        elif token_type == "project_secret":
            project_secret_entries.append((key, data))
        else:
            result.parse_errors += 1
            stale_keys.append(key)
            _record_stale("unknown", result)
            logger.warning("Unknown auth token cache type", cache_key=key[:_LOG_KEY_PREFIX_LEN], token_type=token_type)

    # Verify each group against DB
    stale_keys.extend(_verify_secret_entries(secret_entries, result))
    stale_keys.extend(_verify_personal_entries(personal_entries, result))
    stale_keys.extend(_verify_project_secret_entries(project_secret_entries, result))

    # Delete stale entries
    if stale_keys:
        _delete_stale_keys(redis_client, stale_keys, result)


def _verify_secret_entries(
    entries: list[tuple[str, dict]],
    result: AuthTokenVerificationResult,
) -> list[str]:
    """Verify Secret token entries. Returns cache keys that are stale."""
    if not entries:
        return []

    stale_keys: list[str] = []

    # Filter out entries missing team_id and collect team_ids for batch query
    valid_entries: list[tuple[str, dict]] = []
    team_ids: set[int] = set()
    for key, data in entries:
        raw_team_id = data.get("team_id")
        if raw_team_id is None:
            stale_keys.append(key)
            _record_stale("secret", result)
            logger.warning("Secret token cache entry missing team_id", cache_key=key[:_LOG_KEY_PREFIX_LEN])
        else:
            try:
                team_id = int(raw_team_id)
            except (ValueError, TypeError):
                result.parse_errors += 1
                stale_keys.append(key)
                _record_stale("secret", result)
                logger.warning(
                    "Secret token cache entry has non-integer team_id",
                    cache_key=key[:_LOG_KEY_PREFIX_LEN],
                    team_id=raw_team_id,
                )
                continue
            valid_entries.append((key, data))
            team_ids.add(team_id)

    if not valid_entries:
        return stale_keys
    try:
        teams = Team.objects.filter(id__in=team_ids).only("id", "secret_api_token", "secret_api_token_backup")
        teams_by_id: dict[int, Team] = {t.id: t for t in teams}
    except Exception as e:
        AUTH_TOKEN_VERIFY_ERRORS_COUNTER.inc()
        capture_exception(e)
        logger.exception("Error querying teams for auth token verification")
        result.db_errors += len(valid_entries)
        return stale_keys

    # Build set of valid token hashes per team
    valid_hashes_by_team: dict[int, set[str]] = {}
    for team_id, team in teams_by_id.items():
        hashes: set[str] = set()
        for token in (team.secret_api_token, team.secret_api_token_backup):
            if token:
                hashes.add(hash_key_value(token, mode="sha256"))
        valid_hashes_by_team[team_id] = hashes

    for key, data in valid_entries:
        team_id = int(data["team_id"])  # already validated as int-castable above
        token_hash = key[len(TOKEN_CACHE_PREFIX) :]

        if team_id not in teams_by_id:
            stale_keys.append(key)
            _record_stale("secret", result)
            continue

        valid_hashes = valid_hashes_by_team.get(team_id, set())
        if token_hash not in valid_hashes:
            stale_keys.append(key)
            _record_stale("secret", result)
            continue

        result.valid += 1

    return stale_keys


def _verify_personal_entries(
    entries: list[tuple[str, dict]],
    result: AuthTokenVerificationResult,
) -> list[str]:
    """Verify Personal token entries. Returns cache keys that are stale."""
    if not entries:
        return []

    stale_keys: list[str] = []

    # The cache key suffix IS the secure_value
    secure_values = [key[len(TOKEN_CACHE_PREFIX) :] for key, _ in entries]

    try:
        paks = (
            PersonalAPIKey.objects.filter(secure_value__in=secure_values)
            .select_related("user")
            .only(
                "secure_value",
                "user_id",  # FK column needed for pak.user_id access
                "scopes",
                "scoped_teams",
                "scoped_organizations",
                "user__id",
                "user__is_active",
            )
        )
        paks_by_sv: dict[str, PersonalAPIKey] = {pak.secure_value: pak for pak in paks if pak.secure_value is not None}
    except Exception as e:
        AUTH_TOKEN_VERIFY_ERRORS_COUNTER.inc()
        capture_exception(e)
        logger.exception("Error querying PAKs for auth token verification")
        result.db_errors += len(entries)
        return stale_keys

    # Batch-load org memberships for all users
    user_ids = {pak.user_id for pak in paks_by_sv.values()}
    try:
        memberships = OrganizationMembership.objects.filter(user_id__in=user_ids).values_list(
            "user_id", "organization_id"
        )
        org_ids_by_user: dict[int, set[str]] = {}
        for user_id, org_id in memberships:
            org_ids_by_user.setdefault(user_id, set()).add(str(org_id))
    except Exception as e:
        AUTH_TOKEN_VERIFY_ERRORS_COUNTER.inc()
        capture_exception(e)
        logger.exception("Error querying org memberships for auth token verification")
        result.db_errors += len(entries)
        # stale_keys is empty here (populated in per-entry loop below);
        # returning stale_keys on DB error is intentional: staleness can't be determined without membership data
        return stale_keys

    for key, data in entries:
        secure_value = key[len(TOKEN_CACHE_PREFIX) :]
        pak = paks_by_sv.get(secure_value)

        if pak is None:
            stale_keys.append(key)
            _record_stale("personal", result)
            continue

        if not pak.user.is_active:
            stale_keys.append(key)
            _record_stale("personal", result)
            continue

        # Rust rejects personal entries with key_id: None; clean them up proactively
        cached_key_id = data.get("key_id")
        if cached_key_id is None:
            stale_keys.append(key)
            _record_stale("personal", result)
            continue

        # Verify key_id matches the DB row; a stale key_id could cause the Rust
        # service to update last_used_at on the wrong PAK.
        if str(cached_key_id) != str(pak.id):
            stale_keys.append(key)
            _record_stale("personal", result)
            continue

        # Verify org_ids match current membership
        raw_org_ids = data.get("org_ids")
        if raw_org_ids is None or not isinstance(raw_org_ids, (list, set, tuple)):
            # Malformed or missing org_ids in cache; treat as stale instead of raising
            result.parse_errors += 1
            stale_keys.append(key)
            _record_stale("personal", result)
            continue
        try:
            cached_org_ids = set(raw_org_ids)
        except TypeError:
            # Unhashable values in org_ids (e.g. nested lists from corrupted cache)
            result.parse_errors += 1
            stale_keys.append(key)
            _record_stale("personal", result)
            continue
        actual_org_ids = org_ids_by_user.get(pak.user_id, set())
        if cached_org_ids != actual_org_ids:
            stale_keys.append(key)
            _record_stale("personal", result)
            continue

        # Verify scopes match
        cached_scopes = _normalize_optional_list(data.get("scopes"))
        actual_scopes = _normalize_optional_list(pak.scopes)
        if cached_scopes != actual_scopes:
            stale_keys.append(key)
            _record_stale("personal", result)
            continue

        # Verify scoped_teams match
        cached_scoped_teams = _normalize_optional_list(data.get("scoped_teams"))
        actual_scoped_teams = _normalize_optional_list(pak.scoped_teams)
        if cached_scoped_teams != actual_scoped_teams:
            stale_keys.append(key)
            _record_stale("personal", result)
            continue

        # Verify scoped_organizations match (Rust serializes as "scoped_orgs")
        cached_scoped_orgs = _normalize_optional_list(data.get("scoped_orgs"))
        actual_scoped_orgs = _normalize_optional_list(pak.scoped_organizations)
        if cached_scoped_orgs != actual_scoped_orgs:
            stale_keys.append(key)
            _record_stale("personal", result)
            continue

        result.valid += 1

    return stale_keys


def _verify_project_secret_entries(
    entries: list[tuple[str, dict]],
    result: AuthTokenVerificationResult,
) -> list[str]:
    """Verify ProjectSecret token entries. Returns cache keys that are stale."""
    if not entries:
        return []

    stale_keys: list[str] = []

    secure_values = [key[len(TOKEN_CACHE_PREFIX) :] for key, _ in entries]

    try:
        psaks = ProjectSecretAPIKey.objects.filter(secure_value__in=secure_values).only(
            "id", "secure_value", "team_id", "scopes"
        )
        psaks_by_sv: dict[str, ProjectSecretAPIKey] = {p.secure_value: p for p in psaks if p.secure_value is not None}
    except Exception as e:
        AUTH_TOKEN_VERIFY_ERRORS_COUNTER.inc()
        capture_exception(e)
        logger.exception("Error querying PSAKs for auth token verification")
        result.db_errors += len(entries)
        return stale_keys

    for key, data in entries:
        secure_value = key[len(TOKEN_CACHE_PREFIX) :]
        psak = psaks_by_sv.get(secure_value)

        if psak is None:
            stale_keys.append(key)
            _record_stale("project_secret", result)
            continue

        # Verify team_id is present and matches (Rust always writes this field)
        cached_team_id = data.get("team_id")
        if cached_team_id is None:
            stale_keys.append(key)
            _record_stale("project_secret", result)
            continue
        try:
            if int(cached_team_id) != psak.team_id:
                stale_keys.append(key)
                _record_stale("project_secret", result)
                continue
        except (ValueError, TypeError):
            result.parse_errors += 1
            stale_keys.append(key)
            _record_stale("project_secret", result)
            continue

        # Verify key_id is present and matches (Rust always writes this field)
        cached_key_id = data.get("key_id")
        if cached_key_id is None or str(cached_key_id) != str(psak.id):
            stale_keys.append(key)
            _record_stale("project_secret", result)
            continue

        # Verify scopes match
        cached_scopes = _normalize_optional_list(data.get("scopes"))
        actual_scopes = _normalize_optional_list(psak.scopes)
        if cached_scopes != actual_scopes:
            stale_keys.append(key)
            _record_stale("project_secret", result)
            continue

        result.valid += 1

    return stale_keys


def _normalize_optional_list(value: list | None) -> list[str] | None:
    """Normalize optional list fields for comparison.

    Converts both None and empty list to None for consistent comparison
    between Rust (which uses Option<Vec>) and Django (which uses ArrayField with null=True).
    """
    if value is None or value == []:
        return None
    return sorted(str(v) for v in value)


def _record_stale(token_type: str, result: AuthTokenVerificationResult) -> None:
    result.stale_found += 1
    result.stale_by_type[token_type] = result.stale_by_type.get(token_type, 0) + 1
    TOMBSTONE_COUNTER.labels(
        namespace="auth_token",
        operation=f"stale_{token_type}",
        component="auth_token_cache_verifier",
    ).inc()


def _delete_stale_keys(
    redis_client: redis_lib.Redis,
    keys: list[str],
    result: AuthTokenVerificationResult,
) -> None:
    """Delete stale cache keys from Redis."""
    try:
        # Defensive guard: only delete keys that belong to this namespace
        safe_keys = [k for k in keys if k.startswith(TOKEN_CACHE_PREFIX)]
        if len(safe_keys) != len(keys):
            logger.warning(
                "Refusing to delete keys outside auth token namespace",
                skipped=len(keys) - len(safe_keys),
            )
            keys = safe_keys
        if not keys:
            return
        redis_client.delete(*keys)
        logger.info("Deleted stale auth token cache entries", count=len(keys))
    except Exception as e:
        result.delete_errors += len(keys)
        AUTH_TOKEN_VERIFY_ERRORS_COUNTER.inc()
        capture_exception(e)
        logger.exception("Error deleting stale auth token cache entries", count=len(keys))
