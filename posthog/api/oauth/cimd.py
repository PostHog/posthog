"""
OAuth Client ID Metadata Document (CIMD)
draft-ietf-oauth-client-id-metadata-document-00

Allows MCP clients to use an HTTPS URL as their client_id. The authorization
server fetches client metadata (name, redirect URIs, logo) from that URL,
removing the need for pre-registration or Dynamic Client Registration.
"""

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
from oauth2_provider.generators import generate_client_secret
from oauth2_provider.models import AbstractApplication

from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthApplication
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
    rate = "30/hour"


CIMD_THROTTLES = [CIMDBurstThrottle(), CIMDSustainedThrottle()]


class CIMDMetadataDocument(TypedDict, total=False):
    client_id: str
    client_name: str
    redirect_uris: list[str]
    logo_uri: str
    grant_types: list[str]
    response_types: list[str]
    token_endpoint_auth_method: str


def is_cimd_client_id(client_id: str | None) -> bool:
    """Check whether a client_id looks like a CIMD URL."""
    if not client_id or not client_id.startswith("https://"):
        return False
    try:
        parsed = urlparse(client_id)
    except Exception:
        return False
    # Must have a path component beyond just "/"
    if not parsed.path or parsed.path == "/":
        return False
    # Must not have fragments or userinfo
    if parsed.fragment or parsed.username or parsed.password:
        return False
    return True


def validate_cimd_url(url: str) -> tuple[bool, str | None]:
    """
    Validate a CIMD URL for safety and spec compliance.

    Returns (True, None) if valid, or (False, error_message).
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL"

    if parsed.scheme != "https":
        return False, "CIMD client_id must use HTTPS"
    if not parsed.path or parsed.path == "/":
        return False, "CIMD client_id must include a path component"
    if parsed.fragment:
        return False, "CIMD client_id must not contain a fragment"
    if parsed.username or parsed.password:
        return False, "CIMD client_id must not contain userinfo"

    # SSRF protection
    allowed, reason = is_url_allowed(url)
    if not allowed:
        return False, f"URL blocked: {reason}"

    return True, None


def _cache_key(url: str) -> str:
    return f"cimd:metadata:{hashlib.sha256(url.encode()).hexdigest()}"


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
    valid, error = validate_cimd_url(url)
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
        )
    except requests.RequestException as e:
        raise CIMDFetchError(f"Failed to fetch metadata: {e}") from e

    try:
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

    # CIMD clients cannot use secret-based auth methods
    auth_method = metadata.get("token_endpoint_auth_method", "none")
    if auth_method in CIMD_FORBIDDEN_AUTH_METHODS:
        raise CIMDValidationError(f"CIMD clients cannot use token_endpoint_auth_method '{auth_method}'")

    cache_ttl = _parse_cache_ttl(response)
    return metadata, cache_ttl


def _create_cimd_application(url: str, metadata: CIMDMetadataDocument) -> OAuthApplication:
    """Create a new OAuthApplication from CIMD metadata."""
    client_name = metadata.get("client_name", "CIMD Client")
    try:
        validate_client_name(client_name)
    except Exception:
        client_name = "CIMD Client"

    redirect_uris = " ".join(metadata["redirect_uris"])
    logo_uri = metadata.get("logo_uri") or None

    return OAuthApplication.objects.create(
        name=client_name,
        redirect_uris=redirect_uris,
        client_type=AbstractApplication.CLIENT_PUBLIC,
        client_secret=generate_client_secret(),
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


def _update_cimd_application(app: OAuthApplication, metadata: CIMDMetadataDocument) -> OAuthApplication:
    """Update an existing OAuthApplication from refreshed CIMD metadata."""
    client_name = metadata.get("client_name")
    if client_name:
        try:
            validate_client_name(client_name)
            app.name = client_name
        except Exception:
            pass  # Keep existing name if new one is invalid

    new_redirect_uris = " ".join(metadata["redirect_uris"])
    app.redirect_uris = new_redirect_uris
    app.logo_uri = metadata.get("logo_uri") or None
    app.cimd_metadata_last_fetched = timezone.now()

    try:
        app.full_clean()
        app.save(update_fields=["name", "redirect_uris", "logo_uri", "cimd_metadata_last_fetched"])
    except ValidationError as e:
        logger.warning("cimd_update_validation_failed", url=app.cimd_metadata_url, error=str(e))
        capture_exception(e)

    return app


def get_or_create_cimd_application(url: str) -> OAuthApplication:
    """
    Resolve a CIMD URL to an OAuthApplication.

    Creates a new application if none exists for this URL.
    Refreshes metadata if the cache has expired.
    """
    cache_key = _cache_key(url)
    cached = cache.get(cache_key)

    # Check for existing application
    app = OAuthApplication.objects.filter(cimd_metadata_url=url).first()

    if app and cached:
        logger.debug("cimd_cache_hit", url=url, app_id=str(app.pk))
        return app

    if app:
        logger.debug("cimd_cache_miss", url=url, app_id=str(app.pk), reason="stale")
    else:
        logger.debug("cimd_cache_miss", url=url, reason="new_client")

    # Need to fetch (or re-fetch) metadata
    try:
        metadata, cache_ttl = fetch_cimd_metadata(url)
        logger.debug("cimd_metadata_fetched", url=url, cache_ttl=cache_ttl, client_name=metadata.get("client_name"))
    except (CIMDFetchError, CIMDValidationError) as e:
        if app:
            logger.warning("cimd_refresh_failed_serving_stale", url=url, error=str(e))
            return app
        logger.warning("cimd_fetch_failed", url=url, error=str(e))
        posthoganalytics.capture(
            distinct_id=url,
            event="cimd_metadata_fetch_failed",
            properties={"cimd_url": url, "error": str(e)},
        )
        raise

    # Update cache
    cache.set(cache_key, True, timeout=cache_ttl)
    logger.debug("cimd_cache_set", url=url, cache_ttl=cache_ttl)

    if app:
        logger.debug("cimd_app_updated", url=url, app_id=str(app.pk))
        posthoganalytics.capture(
            distinct_id=url,
            event="cimd_application_metadata_refreshed",
            properties={
                "cimd_url": url,
                "client_name": metadata.get("client_name"),
                "app_id": str(app.pk),
                "cache_ttl": cache_ttl,
            },
        )
        return _update_cimd_application(app, metadata)

    # Create new application
    try:
        new_app = _create_cimd_application(url, metadata)
        logger.debug("cimd_app_created", url=url, app_id=str(new_app.pk), client_name=new_app.name)
        posthoganalytics.capture(
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
        # Race condition: another request already created this app
        app = OAuthApplication.objects.filter(cimd_metadata_url=url).first()
        if app:
            logger.debug("cimd_app_race_resolved", url=url, app_id=str(app.pk))
            return app
        raise


def get_application_by_client_id(client_id: str) -> OAuthApplication:
    """
    Look up an OAuthApplication by client_id, supporting CIMD URL-form client_ids.

    Raises OAuthApplication.DoesNotExist if not found.
    """
    if is_cimd_client_id(client_id):
        return OAuthApplication.objects.get(cimd_metadata_url=client_id)
    return OAuthApplication.objects.get(client_id=client_id)
