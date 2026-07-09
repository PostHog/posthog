"""
OAuth Client ID Metadata Document (CIMD)
draft-ietf-oauth-client-id-metadata-document-00

Allows MCP clients to use an HTTPS URL as their client_id. The authorization
server fetches client metadata (name, redirect URIs, logo) from that URL,
removing the need for pre-registration or Dynamic Client Registration.
"""

import re
import json
import time
import hashlib
from typing import TypedDict
from urllib.parse import urlparse

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

import requests
import structlog
import posthoganalytics
from celery import shared_task
from oauth2_provider.models import AbstractApplication
from rest_framework.throttling import SimpleRateThrottle

from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import (
    CIMDBlocklistEntry,
    CIMDVerificationToken,
    OAuthApplication,
    find_cimd_verification_token,
)
from posthog.ph_client import ph_scoped_capture
from posthog.rate_limit import IPThrottle
from posthog.scopes import filter_to_unprivileged_scopes
from posthog.security.url_validation import is_url_allowed

from .client_name import sanitize_client_name, validate_client_name

logger = structlog.get_logger(__name__)

# Limits per the CIMD specification
CIMD_MAX_DOCUMENT_SIZE = 5 * 1024  # 5KB
CIMD_FETCH_TIMEOUT_SECONDS = 5

# Cache TTL bounds (seconds)
CIMD_CACHE_DEFAULT_TTL = 3600  # 1 hour
CIMD_CACHE_MIN_TTL = 300  # 5 minutes
CIMD_CACHE_MAX_TTL = 86400  # 24 hours

# Forbidden token_endpoint_auth_method values for CIMD clients (they have no client_secret)
CIMD_FORBIDDEN_AUTH_METHODS = frozenset({"client_secret_post", "client_secret_basic", "client_secret_jwt"})


class CIMDFetchError(Exception):
    """Raised when fetching the CIMD metadata document fails."""

    pass


class CIMDValidationError(Exception):
    """Raised when the CIMD metadata document fails validation."""

    pass


class CIMDBurstThrottle(IPThrottle):
    """Rate limit new CIMD application creation by IP - burst limit."""

    scope = "cimd_burst"
    rate = "5/minute"


class CIMDSustainedThrottle(IPThrottle):
    """Rate limit new CIMD application creation by IP - sustained limit."""

    scope = "cimd_sustained"
    rate = "10/hour"


class CIMDGlobalThrottle(SimpleRateThrottle):
    """Rate limit total new CIMD application creation across all IPs."""

    scope = "cimd_global"
    rate = "100/hour"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": "global"}


CIMD_THROTTLE_CLASSES: list[type[SimpleRateThrottle]] = [CIMDBurstThrottle, CIMDSustainedThrottle, CIMDGlobalThrottle]


class ComPostHogNamespace(TypedDict, total=False):
    verification_token: str
    scopes: list[str]


# Functional form required: "com.posthog" is not a valid Python identifier.
CIMDMetadataDocument = TypedDict(
    "CIMDMetadataDocument",
    {
        "client_id": str,
        "client_name": str,
        "redirect_uris": list[str],
        "logo_uri": str,
        "grant_types": list[str],
        "response_types": list[str],
        "token_endpoint_auth_method": str,
        # Legacy top-level token — still read for backwards compatibility.
        "posthog_verification_token": str,
        # Preferred namespace — takes precedence over the legacy top-level key.
        "com.posthog": ComPostHogNamespace,
    },
    total=False,
)


def validate_cimd_url(url: str | None, *, perform_dns_check: bool = False) -> tuple[bool, str | None]:
    """
    Validate a CIMD URL for format and optionally SSRF safety.

    Returns (True, None) if valid, or (False, error_message).
    Without perform_dns_check this is a cheap string-only check.
    With perform_dns_check=True it also resolves DNS and blocks private IPs.
    """
    if not url or not url.startswith("https://"):
        return False, "CIMD client_id must use HTTPS"

    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL"

    if not parsed.path or parsed.path == "/":
        return False, "CIMD client_id must include a path component"
    if parsed.fragment:
        return False, "CIMD client_id must not contain a fragment"
    if parsed.query:
        return False, "CIMD client_id must not contain query parameters"
    if parsed.username or parsed.password:
        return False, "CIMD client_id must not contain userinfo"

    if perform_dns_check:
        allowed, reason = is_url_allowed(url)
        if not allowed:
            return False, f"URL blocked: {reason}"

    return True, None


def is_cimd_client_id(client_id: str | None) -> bool:
    """Cheap format check: is this a valid CIMD URL shape?"""
    valid, _ = validate_cimd_url(client_id)
    return valid


def _cache_key(url: str) -> str:
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    return f"cimd:metadata:{url_hash}"


def _fetch_lock_key(url: str) -> str:
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    return f"cimd:fetching:{url_hash}"


def _blocked_key(url: str) -> str:
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    return f"cimd:blocked:{url_hash}"


def block_cimd_url(url: str, *, reason: str = "", created_by=None, ttl: int = 86400 * 365) -> None:
    """Add a CIMD URL to the blocklist. Persists in Postgres; Redis is cache."""
    CIMDBlocklistEntry.objects.update_or_create(
        cimd_url=url,
        defaults={"reason": reason, "created_by": created_by},
    )
    cache.set(_blocked_key(url), True, timeout=ttl)


def unblock_cimd_url(url: str) -> None:
    """Remove a CIMD URL from the blocklist."""
    CIMDBlocklistEntry.objects.filter(cimd_url=url).delete()
    cache.delete(_blocked_key(url))


def is_cimd_url_blocked(url: str) -> bool:
    """Check if a CIMD URL has been blocklisted.

    Postgres is source of truth; Redis is a read-through cache so the hot
    path stays a single in-memory lookup. A cache miss falls back to a DB
    read and re-warms the cache, so a Redis flush doesn't expose blocked
    URLs."""
    cached = cache.get(_blocked_key(url))
    if cached is not None:
        return bool(cached)
    blocked = CIMDBlocklistEntry.objects.filter(cimd_url=url).exists()
    cache.set(_blocked_key(url), blocked, timeout=86400 * 365)
    return blocked


def _parse_cache_ttl(response: requests.Response) -> int:
    """Extract cache TTL from HTTP headers, clamped to [min, max]."""
    cache_control = response.headers.get("Cache-Control", "")
    for directive in cache_control.split(","):
        directive = directive.strip().lower()
        if directive.startswith("max-age="):
            try:
                max_age = int(directive.split("=", 1)[1])
                return max(CIMD_CACHE_MIN_TTL, min(max_age, CIMD_CACHE_MAX_TTL))
            except (ValueError, IndexError):
                pass
    return CIMD_CACHE_DEFAULT_TTL


def fetch_cimd_metadata(url: str) -> tuple[CIMDMetadataDocument, int]:
    """
    Fetch and validate a CIMD metadata document.

    Returns (metadata, cache_ttl_seconds).
    Raises CIMDFetchError on network/HTTP errors, CIMDValidationError on invalid content.
    """
    valid, error = validate_cimd_url(url, perform_dns_check=True)
    if not valid:
        raise CIMDValidationError(error)

    try:
        response = requests.get(
            url,
            timeout=CIMD_FETCH_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json",
                "User-Agent": "PostHog-CIMD/1.0",
            },
            stream=True,
            allow_redirects=False,
        )
    except requests.RequestException as e:
        raise CIMDFetchError(f"Failed to fetch metadata: {e}") from e

    try:
        if response.is_redirect or response.is_permanent_redirect:
            raise CIMDFetchError(
                f"Metadata endpoint returned redirect (HTTP {response.status_code}), redirects are not allowed"
            )
        if response.status_code != 200:
            raise CIMDFetchError(f"Metadata endpoint returned HTTP {response.status_code}")

        # Early reject if Content-Length exceeds limit
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > CIMD_MAX_DOCUMENT_SIZE:
                    raise CIMDValidationError(f"Metadata document exceeds {CIMD_MAX_DOCUMENT_SIZE} byte limit")
            except ValueError:
                pass  # Non-numeric Content-Length; fall through to incremental size check

        # Read incrementally to avoid buffering unbounded responses.
        # Also enforce a total transfer deadline so a slow-drip server
        # (1 byte per recv, just under the per-recv timeout) can't keep
        # the connection open indefinitely.
        deadline = time.monotonic() + CIMD_FETCH_TIMEOUT_SECONDS * 2
        chunks: list[bytes] = []
        bytes_read = 0
        for chunk in response.iter_content(chunk_size=4096):
            bytes_read += len(chunk)
            if bytes_read > CIMD_MAX_DOCUMENT_SIZE:
                raise CIMDValidationError(f"Metadata document exceeds {CIMD_MAX_DOCUMENT_SIZE} byte limit")
            chunks.append(chunk)
            if time.monotonic() > deadline:
                raise CIMDFetchError("Metadata fetch exceeded total time limit")
        body = b"".join(chunks)
    finally:
        response.close()

    try:
        metadata: CIMDMetadataDocument = json.loads(body)
    except Exception as e:
        raise CIMDValidationError(f"Invalid JSON in metadata document: {e}") from e

    if not isinstance(metadata, dict):
        raise CIMDValidationError("Metadata document must be a JSON object")

    # client_id MUST match the URL (simple string comparison per spec)
    if metadata.get("client_id") != url:
        raise CIMDValidationError(f"client_id in metadata ({metadata.get('client_id')!r}) does not match URL ({url!r})")

    # redirect_uris required
    redirect_uris = metadata.get("redirect_uris")
    if not redirect_uris or not isinstance(redirect_uris, list) or len(redirect_uris) == 0:
        raise CIMDValidationError("Metadata document must contain a non-empty redirect_uris array")

    for uri in redirect_uris:
        if not isinstance(uri, str) or not uri.strip():
            raise CIMDValidationError("Each redirect_uri must be a non-empty string")

        # Reject whitespace in URIs — they're stored space-separated, so embedded
        # whitespace would be interpreted as multiple redirect URIs by the model.
        if re.search(r"\s", uri):
            raise CIMDValidationError("redirect_uri must not contain whitespace")

    # CIMD clients cannot use secret-based auth methods
    auth_method = metadata.get("token_endpoint_auth_method", "none")
    if auth_method in CIMD_FORBIDDEN_AUTH_METHODS:
        raise CIMDValidationError(f"CIMD clients cannot use token_endpoint_auth_method '{auth_method}'")

    # Validate logo_uri if present: must be HTTPS and pass SSRF checks
    logo_uri = metadata.get("logo_uri")
    if logo_uri:
        if not isinstance(logo_uri, str) or not logo_uri.startswith("https://"):
            metadata.pop("logo_uri", None)
        else:
            logo_allowed, _ = is_url_allowed(logo_uri)
            if not logo_allowed:
                metadata.pop("logo_uri", None)

    cache_ttl = _parse_cache_ttl(response)
    return metadata, cache_ttl


def _resolve_verification_token(metadata: CIMDMetadataDocument) -> CIMDVerificationToken | None:
    """Look up a verification token from CIMD metadata, preferring the nested
    `com.posthog.verification_token` and falling back to the legacy top-level
    `posthog_verification_token`. Falls back to the top-level token when the nested
    one is absent OR present-but-unrecognized, so a typo'd nested token doesn't drop
    a partner whose legacy token still resolves. Returns the token record, or None."""
    com_posthog = metadata.get("com.posthog")
    if isinstance(com_posthog, dict):
        nested_raw = com_posthog.get("verification_token")
        if nested_raw and isinstance(nested_raw, str):
            token = find_cimd_verification_token(nested_raw)
            if token is not None:
                return token

    raw = metadata.get("posthog_verification_token")
    if not raw or not isinstance(raw, str):
        return None
    return find_cimd_verification_token(raw)


def _resolve_scopes(metadata: CIMDMetadataDocument) -> list[str] | None:
    """Resolve the allow-listed `com.posthog.scopes` for an app, or None when the field
    is absent so callers leave existing scopes untouched. A present field returns a
    (possibly empty) list, capped to grantable scopes by `filter_to_unprivileged_scopes`.

    Raises CIMDValidationError when the field is present and non-empty but every entry is
    non-grantable. An empty ceiling falls back to the broad UNPRIVILEGED_SCOPES default
    (`effective_ceiling`), so silently storing `[]` here would widen a misconfigured app
    to the full default surface — broader than it asked for. Reject it the way DCR rejects
    an all-stripped `scope` string, so the partner fixes their metadata. An explicitly empty
    list is left as the legitimate "use default" signal, same as an absent field.
    """
    com_posthog = metadata.get("com.posthog")
    if not isinstance(com_posthog, dict):
        return None
    # Untrusted partner JSON: the TypedDict says list[str], but guard the real type.
    raw_scopes: object = com_posthog.get("scopes")
    if not isinstance(raw_scopes, list):
        return None
    filtered = filter_to_unprivileged_scopes(raw_scopes)
    if raw_scopes and not filtered:
        raise CIMDValidationError(
            "None of the declared com.posthog.scopes are available to self-registered clients. "
            "Remove the field to register with the default scope set."
        )
    return filtered


def _resolve_optional_scopes(metadata: CIMDMetadataDocument) -> list[str] | None:
    """Resolve `com.posthog.optional_scopes` — the declinable subset a partner offers on top
    of its required `scopes`, so a CIMD client gets the same required/optional consent split as
    any other app. Returns None when the field is absent (leave existing scopes untouched),
    otherwise the grantable-filtered list. Unlike `scopes`, an empty result is benign (it just
    means no optional scopes, with no widen-to-default fallback), so a fully non-grantable list
    resolves to `[]` rather than rejecting the registration.
    """
    com_posthog = metadata.get("com.posthog")
    if not isinstance(com_posthog, dict):
        return None
    # Untrusted partner JSON: guard the real type rather than trust the TypedDict.
    raw_optional: object = com_posthog.get("optional_scopes")
    if not isinstance(raw_optional, list):
        return None
    return filter_to_unprivileged_scopes(raw_optional)


def _create_cimd_application(url: str, metadata: CIMDMetadataDocument) -> OAuthApplication:
    """Create a new OAuthApplication from CIMD metadata."""
    client_name = metadata.get("client_name", "CIMD Client")
    try:
        validate_client_name(client_name)
    except Exception:
        client_name = "CIMD Client"
    # Escape the partner-controlled name so the stored value is HTML-safe in any sink.
    client_name = sanitize_client_name(client_name)

    redirect_uris = " ".join(metadata.get("redirect_uris", []))
    logo_uri = metadata.get("logo_uri") or None
    verification = _resolve_verification_token(metadata)
    resolved_scopes = _resolve_scopes(metadata)
    resolved_optional_scopes = _resolve_optional_scopes(metadata)

    app = OAuthApplication(
        name=client_name,
        redirect_uris=redirect_uris,
        client_type=AbstractApplication.CLIENT_PUBLIC,
        client_secret="",
        authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE,
        algorithm="RS256",
        skip_authorization=False,
        is_cimd_client=True,
        cimd_metadata_url=url,
        cimd_metadata_last_fetched=timezone.now(),
        logo_uri=logo_uri,
        organization=verification.organization if verification else None,
        scopes=resolved_scopes if resolved_scopes is not None else [],
        optional_scopes=resolved_optional_scopes if resolved_optional_scopes is not None else [],
        user=None,
    )
    app.full_clean()
    app.save()
    if verification is not None:
        _touch_verification_token(verification)
    return app


TOUCH_VERIFICATION_TOKEN_MIN_INTERVAL = 300  # 5 minutes


def _touch_verification_token(token: CIMDVerificationToken) -> None:
    # Bump last_used_at at most once per TOUCH_VERIFICATION_TOKEN_MIN_INTERVAL
    # per token to avoid vacuum / lock-contention pressure on busy partners.
    sentinel_key = f"cimd:token_touched:{token.pk}"
    if not cache.add(sentinel_key, True, timeout=TOUCH_VERIFICATION_TOKEN_MIN_INTERVAL):
        return
    CIMDVerificationToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())


def _update_cimd_application(app: OAuthApplication, metadata: CIMDMetadataDocument) -> OAuthApplication:
    """
    Update an existing OAuthApplication from refreshed CIMD metadata.

    On validation failure, refreshes from the database so the caller never
    sees a partially-mutated in-memory object.
    """
    client_name = metadata.get("client_name")
    if client_name:
        try:
            validate_client_name(client_name)
            app.name = sanitize_client_name(client_name)
        except Exception:
            pass  # Keep existing name if new one is invalid

    app.redirect_uris = " ".join(metadata.get("redirect_uris", []))
    app.logo_uri = new_uri if (new_uri := metadata.get("logo_uri")) is not None else app.logo_uri
    app.cimd_metadata_last_fetched = timezone.now()

    # Re-evaluate verification on every refresh so a rotated/removed token
    # unlinks the app on the next fetch.
    verification = _resolve_verification_token(metadata)
    new_org = verification.organization if verification else None
    update_fields = ["name", "redirect_uris", "logo_uri", "cimd_metadata_last_fetched"]

    resolved_scopes = _resolve_scopes(metadata)
    if resolved_scopes is not None:
        app.scopes = resolved_scopes
        update_fields.append("scopes")
    # Refresh `optional_scopes` from the same metadata so the required/optional split never
    # drifts: both fields are rewritten together on every fetch.
    resolved_optional_scopes = _resolve_optional_scopes(metadata)
    if resolved_optional_scopes is not None:
        app.optional_scopes = resolved_optional_scopes
        update_fields.append("optional_scopes")
    old_org_id = app.organization_id
    new_org_id = new_org.id if new_org else None
    if old_org_id != new_org_id:
        app.organization = new_org
        update_fields.append("organization")
        # When verification status flips on an already-provisioning app, keep
        # the rate-limit tier in sync. Only bump when the source is one of our
        # default tiers — explicit admin overrides (source="admin") and
        # legacy rows with no source recorded (source="") stay put. Legacy
        # rows are treated conservatively as admin to avoid clobbering values
        # that pre-date this field.
        if app.is_provisioning_partner and app.provisioning_rate_limit_account_requests_source in (
            "default_unverified",
            "default_verified",
        ):
            became_verified = old_org_id is None and new_org_id is not None
            became_unverified = old_org_id is not None and new_org_id is None
            if became_verified:
                app.provisioning_rate_limit_account_requests = CIMD_PROVISIONING_ACCOUNT_REQUESTS_VERIFIED_RATE_LIMIT
                app.provisioning_rate_limit_account_requests_source = "default_verified"
                update_fields.extend(
                    ["provisioning_rate_limit_account_requests", "provisioning_rate_limit_account_requests_source"]
                )
            elif became_unverified:
                app.provisioning_rate_limit_account_requests = CIMD_PROVISIONING_ACCOUNT_REQUESTS_DEFAULT_RATE_LIMIT
                app.provisioning_rate_limit_account_requests_source = "default_unverified"
                update_fields.extend(
                    ["provisioning_rate_limit_account_requests", "provisioning_rate_limit_account_requests_source"]
                )

    try:
        app.full_clean()
        app.save(update_fields=update_fields)
    except ValidationError as e:
        logger.warning("cimd_update_validation_failed", url=app.cimd_metadata_url, error=str(e))
        capture_exception(e)
        # Refresh from DB so we don't return a mutated-but-unsaved object
        app.refresh_from_db()
    else:
        if verification is not None:
            _touch_verification_token(verification)
        # Emit a distinct event on org re-linking so a metadata compromise
        # flipping A→B (or A→None, None→A) is visible in analytics, not
        # just buried in the generic refresh event.
        if old_org_id != new_org_id:
            posthoganalytics.capture(
                distinct_id=app.cimd_metadata_url or str(app.pk),
                event="cimd_application_org_changed",
                properties={
                    "cimd_url": app.cimd_metadata_url,
                    "app_id": str(app.pk),
                    "old_organization_id": str(old_org_id) if old_org_id else None,
                    "new_organization_id": str(new_org_id) if new_org_id else None,
                },
            )

    return app


def fetch_and_upsert_cimd_application(url: str, capture_ph_event=posthoganalytics.capture) -> OAuthApplication | None:
    """
    Fetch CIMD metadata and create or update the application.

    Uses a cache-based lock to coalesce concurrent calls for the same URL.
    Returns the created/updated app, or None if the lock couldn't be acquired
    (meaning another caller is already handling it).

    Used by both synchronous (new client) and asynchronous (stale refresh) paths.
    """
    if is_cimd_url_blocked(url):
        logger.warning("cimd_blocked_url_fetch_attempt", url=url)
        return None

    fetch_lock = _fetch_lock_key(url)
    if not cache.add(fetch_lock, True, timeout=CIMD_FETCH_TIMEOUT_SECONDS * 3):
        return None

    try:
        metadata, cache_ttl = fetch_cimd_metadata(url)
        cache.set(_cache_key(url), True, timeout=cache_ttl)

        app = OAuthApplication.objects.filter(cimd_metadata_url=url).first()
        if app:
            updated = _update_cimd_application(app, metadata)
            logger.debug("cimd_app_updated", url=url, app_id=str(updated.pk))
            capture_ph_event(
                distinct_id=url,
                event="cimd_application_metadata_refreshed",
                properties={
                    "cimd_url": url,
                    "client_name": metadata.get("client_name"),
                    "app_id": str(updated.pk),
                    "cache_ttl": cache_ttl,
                    "is_verified": updated.organization_id is not None,
                    "organization_id": str(updated.organization_id) if updated.organization_id else None,
                },
            )
            return updated

        try:
            new_app = _create_cimd_application(url, metadata)
            logger.debug("cimd_app_created", url=url, app_id=str(new_app.pk), client_name=new_app.name)
            capture_ph_event(
                distinct_id=url,
                event="cimd_application_created",
                properties={
                    "cimd_url": url,
                    "client_name": new_app.name,
                    "app_id": str(new_app.pk),
                    "redirect_uris_count": len(metadata.get("redirect_uris", [])),
                    "has_logo": bool(metadata.get("logo_uri")),
                    "cache_ttl": cache_ttl,
                    "is_verified": new_app.organization_id is not None,
                    "organization_id": str(new_app.organization_id) if new_app.organization_id else None,
                    "had_verification_token_attempt": bool(
                        metadata.get("posthog_verification_token")
                        or (isinstance(ns := metadata.get("com.posthog"), dict) and ns.get("verification_token"))
                    ),
                },
            )
            return new_app
        except (IntegrityError, ValidationError):
            app = OAuthApplication.objects.filter(cimd_metadata_url=url).first()
            if app:
                logger.debug("cimd_app_race_resolved", url=url, app_id=str(app.pk))
                return app
            raise
    finally:
        cache.delete(fetch_lock)


@shared_task(ignore_result=True, time_limit=30)
def refresh_cimd_metadata_task(url: str) -> None:
    """Celery task wrapper: refresh CIMD metadata in the background."""
    try:
        with ph_scoped_capture() as capture_ph_event:
            fetch_and_upsert_cimd_application(url, capture_ph_event=capture_ph_event)
    except CIMDValidationError as e:
        # Expected rejection of a non-compliant partner document — log for observability, don't surface as an error.
        logger.warning("cimd_background_refresh_failed", url=url, error=str(e))
    except CIMDFetchError as e:
        logger.warning("cimd_background_refresh_failed", url=url, error=str(e))
        capture_exception(e)


@shared_task(ignore_result=True, time_limit=30)
def register_cimd_provisioning_application_task(url: str) -> None:
    """Celery task: fetch CIMD metadata, create the app, and backfill provisioning defaults."""
    try:
        with ph_scoped_capture() as capture_ph_event:
            app = fetch_and_upsert_cimd_application(url, capture_ph_event=capture_ph_event)
            if app is None:
                return
            if not app.is_provisioning_partner:
                apply_provisioning_defaults(app)
                capture_ph_event(
                    distinct_id=url,
                    event="cimd_provisioning_partner_registered",
                    properties={
                        "cimd_url": url,
                        "client_name": app.name,
                        "app_id": str(app.pk),
                        "account_requests_rate_limit": app.provisioning_rate_limit_account_requests,
                        "is_verified": app.organization_id is not None,
                        "organization_id": str(app.organization_id) if app.organization_id else None,
                    },
                )
    except CIMDValidationError as e:
        # Expected rejection of a non-compliant partner document — log for observability, don't surface as an error.
        logger.warning("cimd_background_registration_failed", url=url, error=str(e))
    except CIMDFetchError as e:
        logger.warning("cimd_background_registration_failed", url=url, error=str(e))
        capture_exception(e)


def is_cimd_registration_in_progress(url: str) -> bool:
    """Check if a fetch/registration is currently in progress for this CIMD URL."""
    return bool(cache.get(_fetch_lock_key(url)))


def get_or_create_cimd_application(url: str) -> OAuthApplication:
    """
    Resolve a CIMD URL to an OAuthApplication.

    - Cache fresh + app exists: return immediately
    - App exists + cache stale: return stale app, refresh in background
    - No app: fetch synchronously (must have the app before proceeding)
    """
    # Existing client: check cache freshness and if not fresh, fire refresh in the background, returning existing app immediately
    if app := OAuthApplication.objects.filter(cimd_metadata_url=url).first():
        enqueue_cimd_refresh_if_stale(url)
        return app

    # New client: synchronous fetch
    if app := fetch_and_upsert_cimd_application(url):
        return app

    # Lock was held — another request is already creating this app.
    # Poll the DB until it appears or we give up.
    for _ in range(CIMD_FETCH_TIMEOUT_SECONDS + 1):
        time.sleep(1)
        app = OAuthApplication.objects.filter(cimd_metadata_url=url).first()
        if app:
            return app

    raise CIMDFetchError(f"Another request is already registering this client ({url}). Please try again.")


def enqueue_cimd_refresh_if_stale(url: str) -> None:
    """Fire a background metadata refresh if the cached document has gone stale.

    Single source of the freshness check, used both by get_or_create_cimd_application
    and by callers that resolve an existing CIMD app via a direct lookup (the agentic
    provisioning auth path) so document changes are picked up on the same TTL, instead
    of freezing the app's scopes and config at first registration.
    """
    if not cache.get(_cache_key(url)):
        refresh_cimd_metadata_task.delay(url)


def get_application_by_client_id(client_id: str) -> OAuthApplication:
    """
    Look up an OAuthApplication by client_id, supporting CIMD URL-form client_ids.

    Raises OAuthApplication.DoesNotExist if not found.
    """
    if is_cimd_client_id(client_id):
        return OAuthApplication.objects.get(cimd_metadata_url=client_id)
    return OAuthApplication.objects.get(client_id=client_id)


# Defaults applied when a CIMD app is first used for provisioning. A self-serve
# partner can hit /account_requests immediately without manual admin setup; the
# app is opted into provisioning at the same trust level as other PKCE partners.
# The account-request rate limit is set to a conservative floor so a single
# self-serve partner cannot burn through bulk user-onboarding calls — admin can
# raise it per-partner once a partner demonstrates legitimate volume. Verified
# partners (those who presented a valid `posthog_verification_token`) get a
# higher default since abuse is traceable to a real PostHog organization.
CIMD_PROVISIONING_ACCOUNT_REQUESTS_DEFAULT_RATE_LIMIT = 10  # per hour, anonymous CIMD
CIMD_PROVISIONING_ACCOUNT_REQUESTS_VERIFIED_RATE_LIMIT = 100  # per hour, verified CIMD
CIMD_PROVISIONING_DEFAULTS = {
    "provisioning_auth_method": "pkce",
    "provisioning_active": True,
    "provisioning_can_create_accounts": True,
    "provisioning_can_provision_resources": True,
    "provisioning_rate_limit_account_requests": CIMD_PROVISIONING_ACCOUNT_REQUESTS_DEFAULT_RATE_LIMIT,
}


def _cimd_provisioning_defaults_for(app: OAuthApplication) -> dict:
    """Return the provisioning default profile to apply to this CIMD app on
    first-time registration. Verified apps (linked to a PostHog org) get the
    higher account-request rate limit."""
    defaults = dict(CIMD_PROVISIONING_DEFAULTS)
    if app.organization_id is not None:
        defaults["provisioning_rate_limit_account_requests"] = CIMD_PROVISIONING_ACCOUNT_REQUESTS_VERIFIED_RATE_LIMIT
        defaults["provisioning_rate_limit_account_requests_source"] = "default_verified"
    else:
        defaults["provisioning_rate_limit_account_requests_source"] = "default_unverified"
    return defaults


def apply_provisioning_defaults(app: OAuthApplication) -> OAuthApplication:
    """Apply provisioning defaults to a CIMD app and persist them.

    Computes the correct defaults (verified vs anonymous rate limit) based on
    the app's organization linkage, sets the fields, and saves. Respects
    `provisioning_disabled` as a kill switch - returns the app untouched
    rather than re-enabling a partner an admin has explicitly disabled."""
    if app.provisioning_disabled:
        return app
    defaults = _cimd_provisioning_defaults_for(app)
    for field, value in defaults.items():
        setattr(app, field, value)
    app.save(update_fields=list(defaults.keys()))
    return app


def get_or_create_cimd_provisioning_application(url: str) -> OAuthApplication | None:
    """
    Resolve a CIMD URL to an OAuthApplication configured as a provisioning partner.

    Creates the CIMD app via the normal fetch+upsert path if it doesn't exist,
    then backfills provisioning defaults if they haven't been set. Existing apps
    that already have provisioning fields configured (e.g. via admin) are left alone.

    Returns None if the URL is blocklisted.
    Raises CIMDFetchError / CIMDValidationError on fetch failures.
    """
    if is_cimd_url_blocked(url):
        logger.warning("cimd_blocked_url", url=url)
        return None

    app = get_or_create_cimd_application(url)
    if not app.is_provisioning_partner:
        apply_provisioning_defaults(app)
        posthoganalytics.capture(
            distinct_id=url,
            event="cimd_provisioning_partner_registered",
            properties={
                "cimd_url": url,
                "client_name": app.name,
                "app_id": str(app.pk),
                "account_requests_rate_limit": app.provisioning_rate_limit_account_requests,
                "is_verified": app.organization_id is not None,
                "organization_id": str(app.organization_id) if app.organization_id else None,
            },
        )
    return app
