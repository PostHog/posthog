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
from posthog.models.oauth import OAuthApplication
from posthog.ph_client import ph_scoped_capture
from posthog.rate_limit import IPThrottle
from posthog.security.url_validation import is_url_allowed

from .dcr import validate_client_name

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


class CIMDMetadataDocument(TypedDict, total=False):
    client_id: str
    client_name: str
    redirect_uris: list[str]
    logo_uri: str
    grant_types: list[str]
    response_types: list[str]
    token_endpoint_auth_method: str


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


def block_cimd_url(url: str, ttl: int = 86400 * 365) -> None:
    """Add a CIMD URL to the blocklist. Used by admin to prevent re-registration after deletion."""
    cache.set(_blocked_key(url), True, timeout=ttl)


def unblock_cimd_url(url: str) -> None:
    """Remove a CIMD URL from the blocklist."""
    cache.delete(_blocked_key(url))


def is_cimd_url_blocked(url: str) -> bool:
    """Check if a CIMD URL has been blocklisted."""
    return bool(cache.get(_blocked_key(url)))


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


def _create_cimd_application(url: str, metadata: CIMDMetadataDocument) -> OAuthApplication:
    """Create a new OAuthApplication from CIMD metadata."""
    client_name = metadata.get("client_name", "CIMD Client")
    try:
        validate_client_name(client_name)
    except Exception:
        client_name = "CIMD Client"

    redirect_uris = " ".join(metadata.get("redirect_uris", []))
    logo_uri = metadata.get("logo_uri") or None

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
        organization=None,
        user=None,
    )
    app.full_clean()
    app.save()
    return app


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
            app.name = client_name
        except Exception:
            pass  # Keep existing name if new one is invalid

    app.redirect_uris = " ".join(metadata.get("redirect_uris", []))
    app.logo_uri = new_uri if (new_uri := metadata.get("logo_uri")) is not None else app.logo_uri
    app.cimd_metadata_last_fetched = timezone.now()

    try:
        app.full_clean()
        app.save(update_fields=["name", "redirect_uris", "logo_uri", "cimd_metadata_last_fetched"])
    except ValidationError as e:
        logger.warning("cimd_update_validation_failed", url=app.cimd_metadata_url, error=str(e))
        capture_exception(e)
        # Refresh from DB so we don't return a mutated-but-unsaved object
        app.refresh_from_db()

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
    except (CIMDFetchError, CIMDValidationError) as e:
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
                for field, value in CIMD_PROVISIONING_DEFAULTS.items():
                    setattr(app, field, value)
                app.save(update_fields=list(CIMD_PROVISIONING_DEFAULTS.keys()))
                capture_ph_event(
                    distinct_id=url,
                    event="cimd_provisioning_partner_registered",
                    properties={
                        "cimd_url": url,
                        "client_name": app.name,
                        "app_id": str(app.pk),
                        "account_requests_rate_limit": CIMD_PROVISIONING_ACCOUNT_REQUESTS_DEFAULT_RATE_LIMIT,
                    },
                )
    except (CIMDFetchError, CIMDValidationError) as e:
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
        if not cache.get(_cache_key(url)):
            refresh_cimd_metadata_task.delay(url)
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
# raise it per-partner once a partner demonstrates legitimate volume.
CIMD_PROVISIONING_ACCOUNT_REQUESTS_DEFAULT_RATE_LIMIT = 10  # per hour
CIMD_PROVISIONING_DEFAULTS = {
    "provisioning_auth_method": "pkce",
    "provisioning_active": True,
    "provisioning_can_create_accounts": True,
    "provisioning_can_provision_resources": True,
    "provisioning_rate_limit_account_requests": CIMD_PROVISIONING_ACCOUNT_REQUESTS_DEFAULT_RATE_LIMIT,
}


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
        for field, value in CIMD_PROVISIONING_DEFAULTS.items():
            setattr(app, field, value)
        app.save(update_fields=list(CIMD_PROVISIONING_DEFAULTS.keys()))
        posthoganalytics.capture(
            distinct_id=url,
            event="cimd_provisioning_partner_registered",
            properties={
                "cimd_url": url,
                "client_name": app.name,
                "app_id": str(app.pk),
                "account_requests_rate_limit": CIMD_PROVISIONING_ACCOUNT_REQUESTS_DEFAULT_RATE_LIMIT,
            },
        )
    return app
