"""Trust for OIDC issuers outside the provider registry, where an admin names the claims a policy checks.

PostHog fetches an issuer's discovery document and keys only through the hardened client-document fetcher,
which refuses private addresses, pins the resolved IPs and follows no redirects. The exchange only ever
fetches an issuer that an enabled policy of the requested project names, so a token can't make PostHog
fetch an arbitrary URL.
"""

from __future__ import annotations

import re
import hashlib
import ipaddress
from typing import Any
from urllib.parse import urlsplit

from django.core.cache import cache

from posthog.dataclasses import frozen
from posthog.jwt import ASYMMETRIC_SIGNING_ALGORITHMS
from posthog.workload_identity.providers import (
    WILDCARD_CHARACTERS,
    AudienceCheck,
    WorkloadClaim,
    WorkloadProvider,
    WorkloadProviderKey,
    get_workload_provider_by_issuer,
)

CUSTOM_PROVIDER_NAME = str(WorkloadProviderKey.CUSTOM.label)
CUSTOM_PROVIDER_DOCS_URL = "https://posthog.com/docs/api/workload-identity/custom"
DEFAULT_SUBJECT_CLAIM = "sub"
DISCOVERY_PATH = "/.well-known/openid-configuration"
DISCOVERY_MAX_BYTES = 64 * 1024
DISCOVERY_CACHE_TTL_SECONDS = 60 * 60
# A failed discovery is remembered briefly, so tokens naming a broken issuer can't turn each exchange into a fetch.
DISCOVERY_FAILURE_TTL_SECONDS = 60
# Another issuer's ID tokens can live for hours or longer. A leaked one keeps minting PostHog tokens until it
# expires, so the exchange refuses a token meant to live longer than this.
CUSTOM_TOKEN_MAX_LIFETIME_SECONDS = 60 * 60
# Registered JWT claims that say how a token is valid, not who sent it, so a policy can't check them.
RESERVED_CLAIMS = frozenset({"iss", "aud", "exp", "iat", "nbf", "jti", "azp", "nonce"})
# Printable ASCII without spaces, as claim names such as https://example.com/claims/team need.
_CLAIM_NAME = re.compile(r"[\x21-\x7e]{1,100}")


class CustomIssuerError(Exception):
    """The issuer can't be trusted. The message is safe to show the admin."""


class CustomIssuerUnavailable(CustomIssuerError):
    """The issuer didn't answer, so a later try may work."""


@frozen
class CustomIssuerMetadata:
    issuer: str
    jwks_uri: str
    # The asymmetric algorithms the issuer says it signs ID tokens with. Empty when it doesn't say.
    signing_algorithms: tuple[str, ...]


def _check_https_url(url: str, what: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise CustomIssuerError(f"The {what} must be an https:// URL.")
    if parts.username or parts.password:
        raise CustomIssuerError(f"The {what} must not contain a user name or password.")
    if parts.fragment:
        raise CustomIssuerError(f"The {what} must not contain a fragment.")
    try:
        ipaddress.ip_address(parts.hostname)
    except ValueError:
        return
    raise CustomIssuerError(f"The {what} must use a host name, not an IP address.")


def validate_custom_issuer_url(issuer: str) -> str:
    """The issuer exactly as tokens must carry it in `iss`, or raise."""
    if issuer != issuer.strip() or not issuer:
        raise CustomIssuerError("Enter the issuer URL without spaces around it.")
    if len(issuer) > 255:
        raise CustomIssuerError("The issuer URL can be at most 255 characters long.")
    _check_https_url(issuer, "issuer URL")
    if urlsplit(issuer).query:
        raise CustomIssuerError("The issuer URL must not contain a query.")
    if get_workload_provider_by_issuer(issuer) is not None:
        raise CustomIssuerError("This issuer is a supported provider. Pick it in the provider list instead.")
    return issuer


def validate_claim_name(name: Any, what: str) -> str:
    if not isinstance(name, str) or not _CLAIM_NAME.fullmatch(name) or WILDCARD_CHARACTERS & set(name):
        raise CustomIssuerError(f"The {what} must be a claim name of up to 100 printable characters, without spaces.")
    if name in RESERVED_CLAIMS:
        raise CustomIssuerError(f"The {what} can't be {name}, which says how a token is valid, not who sent it.")
    return name


def _cache_key(issuer: str) -> str:
    return f"workload_custom_issuer:{hashlib.sha256(issuer.encode()).hexdigest()}"


def _fetch_metadata(issuer: str) -> CustomIssuerMetadata:
    # posthog.api.oauth imports the token exchange, which imports this module.
    from posthog.api.oauth.cimd import (  # noqa: PLC0415 - breaks the import cycle through posthog.api.oauth
        CIMDFetchError,
        CIMDValidationError,
        fetch_client_json_document,
    )

    try:
        document, _ = fetch_client_json_document(
            f"{issuer.rstrip('/')}{DISCOVERY_PATH}",
            what="OpenID configuration",
            max_size=DISCOVERY_MAX_BYTES,
            user_agent="PostHog-Workload-Identity/1.0",
            require_identity_url_shape=False,
        )
    except CIMDValidationError as e:
        raise CustomIssuerError(f"PostHog can't read the issuer's OpenID configuration: {e}")
    except CIMDFetchError as e:
        raise CustomIssuerUnavailable(f"PostHog couldn't fetch the issuer's OpenID configuration: {e}")
    if document.get("issuer") != issuer:
        raise CustomIssuerError(
            "The issuer's OpenID configuration names another issuer. Enter the issuer URL exactly as its tokens carry it."
        )
    jwks_uri = document.get("jwks_uri")
    if not isinstance(jwks_uri, str):
        raise CustomIssuerError("The issuer's OpenID configuration has no jwks_uri.")
    _check_https_url(jwks_uri, "jwks_uri in the OpenID configuration")
    advertised = document.get("id_token_signing_alg_values_supported")
    algorithms: tuple[str, ...] = ()
    if isinstance(advertised, list):
        algorithms = tuple(alg for alg in advertised if alg in ASYMMETRIC_SIGNING_ALGORITHMS)
        if not algorithms:
            raise CustomIssuerError(
                "The issuer signs tokens only with algorithms PostHog doesn't accept. PostHog accepts RSA and EC "
                "signatures, such as RS256 and ES256."
            )
    return CustomIssuerMetadata(issuer=issuer, jwks_uri=jwks_uri, signing_algorithms=algorithms)


def discover_custom_issuer(issuer: str, *, refresh: bool = False, retry_failure: bool = False) -> CustomIssuerMetadata:
    """The issuer's keys and algorithms from its discovery document, cached for an hour. `refresh` always
    fetches, and `retry_failure` fetches again only when the cached answer is a failure."""
    validate_custom_issuer_url(issuer)
    key = _cache_key(issuer)
    cached = None if refresh else cache.get(key)
    if isinstance(cached, dict) and "error" in cached and retry_failure:
        cached = None
    if isinstance(cached, dict):
        if "error" in cached:
            error_class = CustomIssuerUnavailable if cached.get("unavailable") else CustomIssuerError
            raise error_class(cached["error"])
        return CustomIssuerMetadata(
            issuer=issuer, jwks_uri=cached["jwks_uri"], signing_algorithms=tuple(cached["signing_algorithms"])
        )
    try:
        metadata = _fetch_metadata(issuer)
    except CustomIssuerError as e:
        failure = {"error": str(e), "unavailable": isinstance(e, CustomIssuerUnavailable)}
        cache.set(key, failure, timeout=DISCOVERY_FAILURE_TTL_SECONDS)
        raise
    cache.set(
        key,
        {"jwks_uri": metadata.jwks_uri, "signing_algorithms": list(metadata.signing_algorithms)},
        timeout=DISCOVERY_CACHE_TTL_SECONDS,
    )
    return metadata


def custom_checked_claims(policy: Any) -> tuple[str, ...]:
    """The claims a custom policy or request checks: its subject claim, name claim and condition claims."""
    return tuple(name for name in (policy.subject_claim, policy.subject_name_claim, *policy.conditions) if name)


def custom_workload_provider(
    issuer: str, *, subject_claim: str, subject_name_claim: str, condition_claims: tuple[str, ...]
) -> WorkloadProvider:
    """A registry-shaped entry for one custom policy, so validation and labels work as for the registry."""
    subject = WorkloadClaim(name=subject_claim, label=subject_claim)
    subject_name = WorkloadClaim(name=subject_name_claim or subject_claim, label=subject_name_claim or "Name")
    conditions = tuple(WorkloadClaim(name=name, label=name) for name in condition_claims)
    return WorkloadProvider(
        key=WorkloadProviderKey.CUSTOM,
        name=CUSTOM_PROVIDER_NAME,
        issuer=issuer,
        jwks_url="",
        audience_check=AudienceCheck.SITE_URL,
        subject_claim=subject,
        subject_name_claim=subject_name,
        condition_claims=conditions,
        recorded_claims=(subject, *conditions) if not subject_name_claim else (subject, subject_name, *conditions),
        actor_label_template="",
        run_url_template=None,
        docs_url=CUSTOM_PROVIDER_DOCS_URL,
    )
