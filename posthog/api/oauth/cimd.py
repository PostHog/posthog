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
from typing import TYPE_CHECKING, TypedDict, cast
from urllib.parse import urlparse

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
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
    TokenEndpointAuthMethod,
    find_cimd_verification_token,
)
from posthog.ph_client import ph_scoped_capture
from posthog.rate_limit import IPThrottle
from posthog.scopes import filter_to_unprivileged_scopes
from posthog.security.pinned_requests import PinnedIPAdapter, select_pinned_ip
from posthog.security.url_validation import is_url_allowed, validate_url_and_pin_ips

from .client_name import sanitize_client_name, validate_client_name

if TYPE_CHECKING:
    from posthog.models.oauth_provisioning import ProvisioningConfig

logger = structlog.get_logger(__name__)

# Limits per the CIMD specification
CIMD_MAX_DOCUMENT_SIZE = 5 * 1024  # 5KB
CIMD_FETCH_TIMEOUT_SECONDS = 5

# Cache TTL bounds (seconds)
CIMD_CACHE_DEFAULT_TTL = 3600  # 1 hour
CIMD_CACHE_MIN_TTL = 300  # 5 minutes
CIMD_CACHE_MAX_TTL = 86400  # 24 hours

# What a CIMD client may register as: public, or confidential via an asymmetric key it
# publishes. Every secret-based method is excluded by omission, because CIMD has no
# registration ceremony in which a shared secret could be delivered. An allowlist rather than
# a denylist so a method added to RFC 7591 later is refused until it is deliberately reviewed.
CIMD_SUPPORTED_AUTH_METHODS = frozenset(
    {TokenEndpointAuthMethod.NONE.value, TokenEndpointAuthMethod.PRIVATE_KEY_JWT.value}
)


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
        "jwks_uri": str,
        # Legacy top-level token — still read for backwards compatibility.
        "posthog_verification_token": str,
        # Preferred namespace — takes precedence over the legacy top-level key.
        "com.posthog": ComPostHogNamespace,
    },
    total=False,
)


def validate_fetchable_https_url(
    url: str | None, *, perform_dns_check: bool = False, what: str = "URL"
) -> tuple[bool, str | None]:
    """Validate that a client-controlled URL is safe for us to dereference.

    Returns (True, None) if valid, or (False, error_message). ``what`` names the URL in those
    messages, since they reach the client that published it.
    Without perform_dns_check this is a cheap string-only check.
    With perform_dns_check=True it also resolves DNS and blocks private IPs.

    These are safety rules only, so they apply to any partner-published document. The
    stricter shape rules that make a URL usable as a CIMD ``client_id`` live in
    :func:`validate_cimd_url`.
    """
    if not url or not url.startswith("https://"):
        return False, f"{what} must use HTTPS"

    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL"

    if parsed.fragment:
        return False, f"{what} must not contain a fragment"
    if parsed.username or parsed.password:
        return False, f"{what} must not contain userinfo"

    if perform_dns_check:
        allowed, reason = is_url_allowed(url)
        if not allowed:
            return False, f"URL blocked: {reason}"

    return True, None


def validate_cimd_url(url: str | None, *, perform_dns_check: bool = False) -> tuple[bool, str | None]:
    """
    Validate a CIMD URL for format and optionally SSRF safety.

    Adds the identity requirements a CIMD ``client_id`` carries on top of the safety checks:
    the URL is the client's stable identifier, so it must name a document (a path) and must
    not vary by query string.
    """
    safe, error = validate_fetchable_https_url(url, perform_dns_check=perform_dns_check, what="CIMD client_id")
    if not safe:
        return False, error

    parsed = urlparse(url or "")
    if not parsed.path or parsed.path == "/":
        return False, "CIMD client_id must include a path component"
    if parsed.query:
        return False, "CIMD client_id must not contain query parameters"

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


def fetch_client_json_document(
    url: str,
    *,
    what: str,
    max_size: int = CIMD_MAX_DOCUMENT_SIZE,
    user_agent: str = "PostHog-CIMD/1.0",
    require_identity_url_shape: bool = True,
) -> tuple[dict, requests.Response]:
    """Fetch a client-controlled JSON document over HTTPS with the full hardening set.

    Shared by the CIMD metadata document and the JWKS a private_key_jwt client publishes,
    so both partner-controlled URLs we dereference get identical protections: SSRF
    validation including a DNS check, no redirects, a byte cap enforced both from
    Content-Length and incrementally, and a total transfer deadline so a slow-drip server
    can't hold a worker open.

    ``require_identity_url_shape`` applies the extra CIMD ``client_id`` shape rules. A
    ``jwks_uri`` is an ordinary document reference rather than an identifier, so it passes
    False and stays free to carry a query string.

    Returns the parsed JSON object and the response, the latter so callers can read cache
    headers. Raises CIMDValidationError for an unsafe URL or oversized/invalid body,
    CIMDFetchError for network and HTTP failures.
    """
    if require_identity_url_shape:
        valid, error = validate_cimd_url(url)
    else:
        valid, error = validate_fetchable_https_url(url, what=what)
    if not valid:
        raise CIMDValidationError(error)

    # The SSRF check resolves the host, and requests would resolve it a second time when
    # it opens the connection. The client controls this URL and its DNS, so it can answer
    # the first lookup with a public address and the second with an internal one. Pinning
    # the connection to the addresses we actually validated closes that rebinding window;
    # PinnedIPAdapter keeps the original hostname for SNI and certificate verification.
    allowed, reason, pinned_ips = validate_url_and_pin_ips(url)
    if not allowed:
        raise CIMDValidationError(f"URL blocked: {reason}")

    adapter = PinnedIPAdapter()
    hostname = (urlparse(url).hostname or "").lower()
    chosen_ip = select_pinned_ip(pinned_ips)
    if chosen_ip is not None:
        adapter.pin(hostname, chosen_ip)

    # Validation above rejects any non-HTTPS URL, so only the https adapter is mounted.
    session = requests.Session()
    session.mount("https://", adapter)

    try:
        response = session.get(
            url,
            timeout=CIMD_FETCH_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json",
                "User-Agent": user_agent,
            },
            stream=True,
            allow_redirects=False,
        )
    except requests.RequestException as e:
        session.close()
        raise CIMDFetchError(f"Failed to fetch {what}: {e}") from e

    try:
        if response.is_redirect or response.is_permanent_redirect:
            raise CIMDFetchError(
                f"{what} endpoint returned redirect (HTTP {response.status_code}), redirects are not allowed"
            )
        if response.status_code != 200:
            raise CIMDFetchError(f"{what} endpoint returned HTTP {response.status_code}")

        # Early reject if Content-Length exceeds limit
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > max_size:
                    raise CIMDValidationError(f"{what} exceeds {max_size} byte limit")
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
            if bytes_read > max_size:
                raise CIMDValidationError(f"{what} exceeds {max_size} byte limit")
            chunks.append(chunk)
            if time.monotonic() > deadline:
                raise CIMDFetchError(f"{what} fetch exceeded total time limit")
        body = b"".join(chunks)
    finally:
        response.close()
        session.close()

    try:
        parsed = json.loads(body)
    except Exception as e:
        raise CIMDValidationError(f"Invalid JSON in {what}: {e}") from e

    if not isinstance(parsed, dict):
        raise CIMDValidationError(f"{what} must be a JSON object")
    return parsed, response


def fetch_cimd_metadata(url: str) -> tuple[CIMDMetadataDocument, int]:
    """
    Fetch and validate a CIMD metadata document.

    Returns (metadata, cache_ttl_seconds).
    Raises CIMDFetchError on network/HTTP errors, CIMDValidationError on invalid content.
    """
    parsed, response = fetch_client_json_document(url, what="Metadata document")
    # The fetcher guarantees a JSON object; whether its keys match the TypedDict is what the
    # validation below establishes.
    metadata = cast(CIMDMetadataDocument, parsed)

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

    # private_key_jwt is the only way for a CIMD client to be confidential: the key is
    # asymmetric, and its public half travels in a document served from the client_id URL
    # itself, so nothing secret has to be delivered out of band.
    auth_method = metadata.get("token_endpoint_auth_method", "none")
    if auth_method not in CIMD_SUPPORTED_AUTH_METHODS:
        raise CIMDValidationError(f"CIMD clients cannot use token_endpoint_auth_method '{auth_method}'")

    jwks_uri = metadata.get("jwks_uri")
    if auth_method == TokenEndpointAuthMethod.PRIVATE_KEY_JWT.value:
        # Without a key source the client could never be authenticated, so accepting the
        # registration would produce a confidential client that fails every request.
        if not jwks_uri or not isinstance(jwks_uri, str):
            raise CIMDValidationError("token_endpoint_auth_method 'private_key_jwt' requires a jwks_uri")
        if not jwks_uri.startswith("https://"):
            raise CIMDValidationError("jwks_uri must be an https URL")
        # A second client-controlled URL we will dereference, so it gets the same SSRF
        # screening as the metadata document itself.
        jwks_allowed, jwks_error = validate_cimd_url(jwks_uri, perform_dns_check=True)
        if not jwks_allowed:
            raise CIMDValidationError(f"jwks_uri is not allowed: {jwks_error}")
    elif jwks_uri is not None:
        # Ignore a key source the client isn't going to authenticate with, rather than
        # storing a URL we would never fetch.
        metadata.pop("jwks_uri", None)

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


def _resolve_client_authentication(metadata: CIMDMetadataDocument) -> tuple[str, str | None]:
    """Map a validated CIMD document's declared auth method onto ``(client_type, jwks_uri)``.

    A client advertising private_key_jwt is confidential in the RFC 6749 sense even though it
    holds no secret, because it can authenticate; everything else is public and relies on PKCE.
    Those two stored fields are what OAuthApplication.token_endpoint_auth_method reads back.

    This is what lets a client upgrade in place: it edits its own metadata document, and the
    next refresh promotes it without the client_id changing or an operator being involved.
    """
    auth_method = metadata.get("token_endpoint_auth_method", TokenEndpointAuthMethod.NONE.value)
    if auth_method == TokenEndpointAuthMethod.PRIVATE_KEY_JWT.value:
        return AbstractApplication.CLIENT_CONFIDENTIAL, metadata.get("jwks_uri")
    return AbstractApplication.CLIENT_PUBLIC, None


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

    client_type, jwks_uri = _resolve_client_authentication(metadata)

    app = OAuthApplication(
        name=client_name,
        redirect_uris=redirect_uris,
        client_type=client_type,
        jwks_uri=jwks_uri,
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


def _retier_account_requests_limit(app: OAuthApplication, *, verified: bool) -> None:
    """Move a partner's account-request limit onto the verified or unverified default tier.

    Only our own default tiers move. An explicit admin override (source="admin") stays put, and
    so does a legacy row with no source recorded, treated conservatively as admin so a value
    that pre-dates the field is not clobbered.

    Locks and re-reads before deciding, because the caller's copy of the app was loaded before a
    network fetch of the metadata document. That window is wide enough for an admin to have
    revoked a capability in it, and merging into a stale blob would write the revoked value back.
    """
    with transaction.atomic():
        current = OAuthApplication.objects.select_for_update().get(pk=app.pk)
        config = current.provisioning
        if not current.is_provisioning_partner or config.rate_limit_source not in (
            "default_unverified",
            "default_verified",
        ):
            return
        app.update_provisioning(
            rate_limits=config.rate_limits.model_copy(
                update={
                    "account_requests": (
                        CIMD_PROVISIONING_ACCOUNT_REQUESTS_VERIFIED_RATE_LIMIT
                        if verified
                        else CIMD_PROVISIONING_ACCOUNT_REQUESTS_DEFAULT_RATE_LIMIT
                    )
                }
            ),
            rate_limit_source="default_verified" if verified else "default_unverified",
        )


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

    # Re-derived on every refresh, in both directions: a client that starts publishing a
    # jwks_uri is promoted to confidential here, and one that stops is demoted back to public
    # rather than being left as a confidential client whose key source has gone away.
    app.client_type, app.jwks_uri = _resolve_client_authentication(metadata)

    # Re-evaluate verification on every refresh so a rotated/removed token
    # unlinks the app on the next fetch.
    verification = _resolve_verification_token(metadata)
    new_org = verification.organization if verification else None
    update_fields = [
        "name",
        "redirect_uris",
        "logo_uri",
        "cimd_metadata_last_fetched",
        "client_type",
        "jwks_uri",
    ]

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
        # Keep the rate-limit tier in step with verification status. Written after the main save
        # and through its own locked merge, rather than as another field on it, because the whole
        # provisioning blob has to be rewritten to change one key inside it.
        if old_org_id is None and new_org_id is not None:
            _retier_account_requests_limit(app, verified=True)
        elif old_org_id is not None and new_org_id is None:
            _retier_account_requests_limit(app, verified=False)
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


# Defaults applied when a CIMD app is opted into provisioning at client_registration. A
# self-serve partner gets there without manual admin setup, at the same trust level as other
# PKCE partners. The account-request rate limit is set to a conservative floor so a single
# self-serve partner cannot burn through bulk user-onboarding calls - admin can raise it
# per-partner once a partner demonstrates legitimate volume. Verified partners (those who
# presented a valid `posthog_verification_token`) get a higher default since abuse is
# traceable to a real PostHog organization.
CIMD_PROVISIONING_ACCOUNT_REQUESTS_DEFAULT_RATE_LIMIT = 10  # per hour, anonymous CIMD
CIMD_PROVISIONING_ACCOUNT_REQUESTS_VERIFIED_RATE_LIMIT = 100  # per hour, verified CIMD


def _cimd_provisioning_defaults_for(app: OAuthApplication) -> "ProvisioningConfig":
    """The config a CIMD app gets when it registers itself, layered over whatever it already has.

    Nothing here touches client authentication: that is derived from the client's own metadata
    document by _resolve_client_authentication, so a CIMD partner is public or private_key_jwt
    according to what it publishes.

    Deliberately narrow. Creating accounts and provisioning resources is the whole point of
    self-serve registration, so those are turned on; no other capability is, because a partner
    that vouched for itself by publishing a document is not the same as one PostHog decided to
    trust. GitHub grants, wizard runs, deep links and skipped consent are granted by an admin or
    not at all.

    Layered rather than replacing the config wholesale, so an admin who granted a capability
    before the app first registered does not have it silently dropped here. For the ordinary
    case - a brand new self-registered client - the existing config is empty and the two are
    the same thing.
    """
    config = app.provisioning
    changes: dict[str, object] = {"active": True, "can_create_accounts": True, "can_provision_resources": True}

    # Verified partners (those who presented a valid `posthog_verification_token`) get a higher
    # account-request limit, since abuse is traceable to a real PostHog organization. An admin
    # override already recorded on the app outranks both tiers.
    if config.rate_limit_source != "admin":
        verified = app.organization_id is not None
        changes["rate_limits"] = config.rate_limits.model_copy(
            update={
                "account_requests": (
                    CIMD_PROVISIONING_ACCOUNT_REQUESTS_VERIFIED_RATE_LIMIT
                    if verified
                    else CIMD_PROVISIONING_ACCOUNT_REQUESTS_DEFAULT_RATE_LIMIT
                )
            }
        )
        changes["rate_limit_source"] = "default_verified" if verified else "default_unverified"

    return config.model_copy(update=changes)


def apply_provisioning_defaults(app: OAuthApplication) -> OAuthApplication:
    """Opt a CIMD app into provisioning with the self-serve defaults, and persist them.

    Respects the `disabled` kill switch - returns the app untouched rather than re-enabling a
    partner an admin has explicitly disabled.

    Locks and re-reads the config first. Registration runs after a network fetch of the metadata
    document, so the caller's copy of the app can be seconds or minutes old, and layering the
    defaults over that copy would write back a capability - or a cleared kill switch - that an
    admin revoked while the fetch was in flight.
    """
    with transaction.atomic():
        current = OAuthApplication.objects.select_for_update().get(pk=app.pk)
        app._provisioning_config = current._provisioning_config
        if app.provisioning.disabled:
            return app
        became_partner = not current.is_provisioning_partner
        app.is_provisioning_partner = True
        app.provisioning = _cimd_provisioning_defaults_for(app)
        app.save(update_fields=["is_provisioning_partner", "_provisioning_config"])

    # A partner appearing without an admin creating it is the event worth watching for abuse,
    # so it fires on the transition only - re-running the defaults over an existing partner is
    # not a new partner.
    if became_partner:
        posthoganalytics.capture(
            distinct_id=app.cimd_metadata_url or str(app.pk),
            event="cimd_provisioning_partner_registered",
            properties={
                "cimd_url": app.cimd_metadata_url,
                "client_name": app.name,
                "app_id": str(app.pk),
                "account_requests_rate_limit": app.provisioning.rate_limits.account_requests,
                "is_verified": app.organization_id is not None,
                "organization_id": str(app.organization_id) if app.organization_id else None,
            },
        )
    return app
