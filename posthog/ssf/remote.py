import json
import time
import hashlib
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.views.decorators.debug import sensitive_variables

import jwt
import httpx
from pydantic import JsonValue
from urllib3.exceptions import InvalidHeader
from urllib3.util.retry import Retry

from posthog.models.ssf import SSFConnection
from posthog.security.pinned_httpx import pinned_client
from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import has_ambiguous_authority, validate_url_and_pin_ips
from posthog.ssf.validation import validate_jwks


class SSFRemoteError(ValueError):
    def __init__(self, message: str, *, retry_after: float | None = None):
        self.retry_after = retry_after
        super().__init__(message)


class SSFRemote:
    MAX_BYTES = 1_048_576
    ENDPOINTS = (
        "configuration_endpoint",
        "status_endpoint",
        "add_subject_endpoint",
        "remove_subject_endpoint",
        "verification_endpoint",
    )

    @staticmethod
    def discovery_url(connection: SSFConnection) -> str:
        if connection.transmitter_url:
            return connection.transmitter_url
        parsed = urlsplit(connection.issuer)
        return urlunsplit(
            (parsed.scheme, parsed.netloc, f"/.well-known/ssf-configuration{parsed.path.rstrip('/')}", "", "")
        )

    @staticmethod
    def validate_url(url: str) -> None:
        try:
            URLValidator(schemes=["https"])(url)
            parsed = urlsplit(url)
            if (
                has_ambiguous_authority(url)
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
            ):
                raise ValueError("Unsafe endpoint URL")
            _ = parsed.port
        except (ValidationError, ValueError) as error:
            raise SSFRemoteError(
                "The transmitter must publish HTTPS endpoints without URL credentials, ambiguous authority, or fragments."
            ) from error

    @staticmethod
    @sensitive_variables("token", "headers", "body", "response", "raw")
    def request(
        method: str,
        url: str,
        *,
        token: str | None = None,
        body: dict[str, JsonValue] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        backoff_key = SSFRemote._cache_key("http-backoff", f"{url}\n{token or ''}")
        retry_at = cache.get(backoff_key)
        if retry_at and retry_at > time.time():
            raise SSFRemoteError(
                "The transmitter is rate limiting requests. Try again later.", retry_after=retry_at - time.time()
            )
        SSFRemote.validate_url(url)
        verdict = validate_url_and_pin_ips(url)
        if not verdict.allowed:
            raise SSFRemoteError(
                "The transmitter endpoint is not a permitted external address. Check its configuration."
            )
        headers = {"Accept": "application/json", "User-Agent": "PostHog-SSF/1.0"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            with pinned_client(
                url,
                verdict.pinned_ips,
                timeout=5,
                total_timeout=10,
                max_response_bytes=SSFRemote.MAX_BYTES,
                follow_redirects=False,
            ) as client:
                with client.stream(method, url, headers=headers, json=body, params=params) as response:
                    if response.status_code == 429:
                        try:
                            delay = Retry().parse_retry_after(response.headers.get("Retry-After", "60"))
                        except (InvalidHeader, ValueError, OverflowError):
                            delay = 60
                        delay = min(max(1, delay), 365 * 86400)
                        cache.set(backoff_key, time.time() + delay, timeout=int(delay))
                        raise SSFRemoteError(
                            "The transmitter is rate limiting requests. Try again later.", retry_after=delay
                        )
                    if not 200 <= response.status_code < 300:
                        raise SSFRemoteError(
                            f"The transmitter returned HTTP {response.status_code}. Check its URL and API credentials."
                        )
                    raw = bytearray()
                    for chunk in response.iter_bytes(chunk_size=4096):
                        raw.extend(chunk)
                        if len(raw) > SSFRemote.MAX_BYTES:
                            raise SSFRemoteError(
                                "The transmitter response exceeds the supported size. Check its configuration."
                            )
                    if not raw:
                        return None
                    return json.loads(raw)
        except (httpx.HTTPError, OSError, SSRFBlockedError) as error:
            raise SSFRemoteError("Could not reach the transmitter. Check its HTTPS endpoint and try again.") from error
        except (json.JSONDecodeError, UnicodeError) as error:
            raise SSFRemoteError("The transmitter returned invalid JSON. Check its configuration.") from error

    @staticmethod
    def _cache_key(kind: str, url: str) -> str:
        return f"ssf:{kind}:{hashlib.sha256(url.encode()).hexdigest()}"

    @staticmethod
    def discover(connection: SSFConnection, *, force: bool = False) -> dict[str, JsonValue]:
        url = SSFRemote.discovery_url(connection)
        key = SSFRemote._cache_key("discovery", url)
        metadata = None if force else cache.get(key)
        if metadata is None:
            document = SSFRemote.request("GET", url)
            if not isinstance(document, dict) or document.get("issuer") != connection.issuer:
                raise SSFRemoteError("The discovered issuer does not exactly match the trusted issuer URL.")
            metadata = {"issuer": connection.issuer}
            for name in ("jwks_uri", *SSFRemote.ENDPOINTS):
                value = document.get(name)
                if value is not None:
                    if not isinstance(value, str):
                        raise SSFRemoteError("The transmitter metadata contains an invalid endpoint URL.")
                    SSFRemote.validate_url(value)
                    metadata[name] = value
            if not metadata.get("jwks_uri") or not metadata.get("configuration_endpoint"):
                raise SSFRemoteError(
                    "The transmitter must publish jwks_uri and configuration_endpoint in its SSF metadata."
                )
            for name in ("delivery_methods_supported", "critical_subject_members"):
                values = document.get(name, [])
                if (
                    not isinstance(values, list)
                    or len(values) > 50
                    or not all(isinstance(value, str) for value in values)
                ):
                    raise SSFRemoteError("The transmitter metadata contains an invalid list of supported capabilities.")
                metadata[name] = values
            cache.set(key, metadata, timeout=300)
        return cast(dict[str, JsonValue], metadata)

    @staticmethod
    @sensitive_variables("document", "cached")
    def keys(connection: SSFConnection, *, refresh: bool = False) -> jwt.PyJWKSet:
        if not connection.jwks_uri:
            if connection.legacy_jwks:
                return jwt.PyJWKSet.from_dict(connection.legacy_jwks)
            raise SSFRemoteError("Refresh the connection to discover the transmitter's signing keys.")
        key = SSFRemote._cache_key("jwks", connection.jwks_uri)
        cached = cache.get(key)
        if refresh and not cache.add(f"{key}:refresh", True, timeout=60):
            if cached and cached != "error":
                return jwt.PyJWKSet.from_dict(cached)
            raise SSFRemoteError("The transmitter's signing keys are temporarily unavailable. Try again later.")
        if not refresh and cached is not None:
            if cached == "error":
                raise SSFRemoteError("The transmitter's signing keys are temporarily unavailable. Try again later.")
            return jwt.PyJWKSet.from_dict(cached)
        try:
            # Key URLs can be on a different host; management credentials must never be forwarded.
            document = validate_jwks(SSFRemote.request("GET", connection.jwks_uri))
        except (SSFRemoteError, ValueError, jwt.PyJWTError, TypeError) as error:
            if cached is None:
                cache.set(key, "error", timeout=30)
            raise SSFRemoteError(
                "Could not retrieve supported public signing keys. Check the transmitter's JWKS endpoint."
            ) from error
        cache.set(key, document, timeout=3600)
        return jwt.PyJWKSet.from_dict(document)

    @staticmethod
    def select_key(connection: SSFConnection, header: dict[str, Any], *, refresh: bool = False) -> jwt.PyJWK:
        keys = SSFRemote.keys(connection, refresh=refresh).keys
        kid = header.get("kid")
        matches = [key for key in keys if key.key_id == kid] if kid is not None else keys
        if len(matches) != 1:
            if kid is not None and not refresh:
                return SSFRemote.select_key(connection, header, refresh=True)
            raise jwt.InvalidKeyError("The security event token is signed by an unknown or ambiguous key.")
        if matches[0].algorithm_name != header.get("alg"):
            raise jwt.InvalidKeyError("The token algorithm does not match its signing key.")
        return matches[0]
