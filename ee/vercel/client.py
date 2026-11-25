import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import caches

import requests
import structlog
from cryptography.fernet import InvalidToken
from requests import HTTPError, RequestException, Timeout
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential, wait_fixed

from posthog.dataclasses import frozen
from posthog.egress.vercel import vercel_request

from ee.api.vercel.crypto import decrypt_payload, encrypt_payload

logger = structlog.get_logger(__name__)

VERCEL_OAUTH_TOKEN_URL = "https://api.vercel.com/v2/oauth/access_token"
INSTALLATION_TOKEN_CACHE_PREFIX = "vercel_installation_token:"
INSTALLATION_TOKEN_CACHE_SALT = "vercel_installation_token"
INSTALLATION_TOKEN_MAX_AGE_SECONDS = 3600
# A cached token must outlive the request it authorizes, including that request's retries.
INSTALLATION_TOKEN_EXPIRY_MARGIN_SECONDS = 300
# Callers include a webhook delivery with an 8 second budget. Two attempts of at most two seconds, plus the
# wait between them, keep a token request under five seconds.
INSTALLATION_TOKEN_ATTEMPTS = 2
INSTALLATION_TOKEN_ATTEMPT_SECONDS = 2
INSTALLATION_TOKEN_LOCK_PREFIX = "vercel_installation_token_lock:"
# The lock outlives the holder's token request, retries included, so it never expires mid-request.
INSTALLATION_TOKEN_LOCK_SECONDS = 5
# A waiter gives up after two seconds and requests its own token, which keeps it inside the webhook budget.
INSTALLATION_TOKEN_LOCK_POLLS = 20
INSTALLATION_TOKEN_LOCK_POLL_SECONDS = 0.1

token_cache = caches["vercel_installation_tokens"]


@frozen
class SSOTokenResponse:
    access_token: str = field(repr=False)
    token_type: str
    id_token: str | None = field(default=None, repr=False)
    scope: str | None = None
    refresh_token: str | None = field(default=None, repr=False)
    error: str | None = None
    error_description: str | None = None


@frozen
class OAuthTokenResponse:
    access_token: str = field(repr=False)
    token_type: str
    installation_id: str
    user_id: str
    team_id: str | None = None
    error: str | None = None
    error_description: str | None = None


@dataclass
class APIError(Exception):
    message: str
    status_code: int | None = None
    detail: str | None = None

    def __str__(self) -> str:
        return f"{self.message} (status: {self.status_code})"


@dataclass(frozen=False)
class InstallationTokenError(APIError):
    code: str | None = None

    @property
    def is_transient(self) -> bool:
        # A transport error carries no status. Any other 4xx than a rate limit is Vercel's answer and stays the
        # same on a retry.
        return self.code != "invalid_response" and (
            self.status_code is None or self.status_code == 429 or self.status_code >= 500
        )


@frozen
class InstallationToken:
    access_token: str = field(repr=False)
    expires_in: int


@dataclass
class OperationResult:
    """Generic result type for Vercel API CRUD operations."""

    success: bool
    item_id: str | None = None
    item_count: int | None = None
    error: str | None = None
    status_code: int | None = None
    error_detail: str | None = None


class VercelAPIClient:
    def __init__(
        self,
        bearer_token: str | None,
        timeout: int = 30,
        base_url: str = "https://api.vercel.com/v1",
        source: str = "integration",
    ):
        self.bearer_token = bearer_token
        self.timeout = timeout
        self.base_url = base_url
        self.source = source
        self.session = requests.Session()

        # Not all endpoints (Such as SSO token exchange) require authorization
        if bearer_token and bearer_token.strip():
            headers = {
                "Authorization": f"Bearer {bearer_token}",
                "Content-Type": "application/json",
            }
            self.session.headers.update(headers)

    @classmethod
    def for_installation(cls, installation_id: str, timeout: int = 30, fresh: bool = False) -> "VercelAPIClient":
        return cls(bearer_token=get_installation_access_token(installation_id, fresh=fresh), timeout=timeout)

    @staticmethod
    def _should_retry_request(exc: BaseException) -> bool:
        is_transient_error = isinstance(exc, (Timeout | requests.ConnectionError))

        if isinstance(exc, HTTPError):
            has_response = exc.response is not None
            is_server_error = has_response and exc.response.status_code >= 500
        else:
            is_server_error = False

        return is_transient_error or is_server_error

    def _parse_json_response(self, response: requests.Response) -> dict[str, Any]:
        try:
            return response.json()
        except json.JSONDecodeError as e:
            logger.exception("Failed to parse JSON response", integration="vercel")
            raise APIError("Invalid JSON response", detail=str(e))

    def _crud_operation(
        self,
        method: str,
        url: str,
        installation_id: str,
        success_msg: str,
        log_kwargs: dict[str, Any],
        result_kwargs: dict[str, Any],
        **request_kwargs,
    ) -> OperationResult:
        try:
            self._request(method, url, installation_id=installation_id, **request_kwargs)
            logger.info(success_msg, integration="vercel", **log_kwargs)
            return OperationResult(success=True, **result_kwargs)
        except APIError as e:
            return OperationResult(success=False, error=e.message, status_code=e.status_code, error_detail=e.detail)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(lambda exc: VercelAPIClient._should_retry_request(exc)),
    )
    def _request(
        self,
        method: str,
        url: str,
        *,
        installation_id: str | None,
        json_body: dict[str, Any] | None = None,
        data: str | None = None,
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
    ) -> requests.Response:
        if json_body is not None:
            data = json.dumps(json_body)
            headers = {**(headers or {}), "Content-Type": "application/json"}
        try:
            response = vercel_request(
                method,
                url,
                source=self.source,
                installation_id=installation_id,
                headers=headers,
                data=data,
                auth=auth,
                session=self.session,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response
        except Timeout as e:
            logger.exception("Request timeout", method=method, url=url, integration="vercel")
            raise APIError("Request timed out", detail=str(e))
        except HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            detail = e.response.text[:500] if e.response is not None else str(e)
            logger.exception("HTTP error", method=method, url=url, status_code=status_code, integration="vercel")
            raise APIError("HTTP error", status_code=status_code, detail=detail)
        except RequestException as e:
            logger.exception("Network error", method=method, url=url, integration="vercel")
            raise APIError("Network error", detail=str(e))

    def create_experimentation_items(
        self, integration_config_id: str, resource_id: str, items: list[dict[str, Any]]
    ) -> OperationResult:
        if not items:
            raise ValueError("items list cannot be empty")

        url = f"{self.base_url}/installations/{integration_config_id}/resources/{resource_id}/experimentation/items"
        return self._crud_operation(
            "POST",
            url,
            integration_config_id,
            "Successfully created experimentation items",
            {"integration_config_id": integration_config_id, "resource_id": resource_id, "item_count": len(items)},
            {"item_count": len(items)},
            json_body={"items": items},
        )

    def update_experimentation_item(
        self, integration_config_id: str, resource_id: str, item_id: str, data: dict[str, Any]
    ) -> OperationResult:
        if not data:
            raise ValueError("data dictionary cannot be empty")

        url = f"{self.base_url}/installations/{integration_config_id}/resources/{resource_id}/experimentation/items/{item_id}"
        return self._crud_operation(
            "PATCH",
            url,
            integration_config_id,
            "Successfully updated experimentation item",
            {"integration_config_id": integration_config_id, "resource_id": resource_id, "item_id": item_id},
            {"item_id": item_id},
            json_body=data,
        )

    def delete_experimentation_item(
        self, integration_config_id: str, resource_id: str, item_id: str
    ) -> OperationResult:
        url = f"{self.base_url}/installations/{integration_config_id}/resources/{resource_id}/experimentation/items/{item_id}"
        return self._crud_operation(
            "DELETE",
            url,
            integration_config_id,
            "Successfully deleted experimentation item",
            {"integration_config_id": integration_config_id, "resource_id": resource_id, "item_id": item_id},
            {"item_id": item_id},
        )

    def _validate_sso_response(self, json_data: dict[str, Any]) -> SSOTokenResponse:
        """Validate and convert SSO token response."""
        if "error" in json_data:
            logger.warning("SSO token exchange API error", error=json_data["error"], integration="vercel")
            return SSOTokenResponse(
                access_token="",
                token_type="",
                error=json_data["error"],
                error_description=json_data.get("error_description"),
            )

        # AFAIK we can miss either access_token or id_token, but not both.
        if not json_data.get("access_token") and not json_data.get("id_token"):
            logger.warning("SSO token exchange missing required fields", integration="vercel")
            return SSOTokenResponse(
                access_token="", token_type="", error="invalid_response", error_description="Missing required fields"
            )

        logger.info("Successfully exchanged SSO token", integration="vercel")
        return SSOTokenResponse(
            access_token=str(json_data["access_token"]),
            token_type=str(json_data["token_type"]),
            id_token=json_data.get("id_token"),
            scope=json_data.get("scope"),
            refresh_token=json_data.get("refresh_token"),
        )

    def import_resource(
        self,
        integration_config_id: str,
        resource_id: str,
        product_id: str,
        name: str,
        secrets: list[dict[str, Any]] | None = None,
    ) -> OperationResult:
        """Register a resource on Vercel's side (upsert). Used after connectable account linking."""
        url = f"{self.base_url}/installations/{integration_config_id}/resources/{resource_id}"
        payload: dict[str, Any] = {
            "productId": product_id,
            "name": name,
            "status": "ready",
            "ownership": "linked",
        }
        if secrets:
            payload["secrets"] = secrets
        return self._crud_operation(
            "PUT",
            url,
            integration_config_id,
            "Successfully imported resource to Vercel",
            {"integration_config_id": integration_config_id, "resource_id": resource_id},
            {},
            json_body=payload,
        )

    def update_resource_secrets(
        self, integration_config_id: str, resource_id: str, secrets: list[dict[str, Any]]
    ) -> OperationResult:
        """Push updated secrets to Vercel for a resource."""
        url = f"{self.base_url}/installations/{integration_config_id}/resources/{resource_id}/secrets"
        return self._crud_operation(
            "PUT",
            url,
            integration_config_id,
            "Successfully updated resource secrets",
            {"integration_config_id": integration_config_id, "resource_id": resource_id},
            {},
            json_body={"secrets": secrets},
        )

    def oauth_token_exchange(
        self,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> OAuthTokenResponse:
        """Exchange an OAuth code for an access token (connectable account flow).

        Uses POST /v2/oauth/access_token (different from the SSO /v1/integrations/sso/token endpoint).
        """
        try:
            response = self._request(
                "POST",
                "https://api.vercel.com/v2/oauth/access_token",
                installation_id=None,
                data=urlencode(
                    {
                        "code": code,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uri": redirect_uri,
                    }
                ),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            json_data = self._parse_json_response(response)

            if "error" in json_data:
                logger.warning("OAuth token exchange error", error=json_data["error"], integration="vercel")
                return OAuthTokenResponse(
                    access_token="",
                    token_type="",
                    installation_id="",
                    user_id="",
                    error=json_data["error"],
                    error_description=json_data.get("error_description"),
                )

            access_token = json_data.get("access_token")
            token_type = json_data.get("token_type")
            installation_id = json_data.get("installation_id")
            user_id = json_data.get("user_id")

            if not access_token or not installation_id or not user_id:
                logger.warning(
                    "OAuth token exchange missing required fields",
                    has_access_token=bool(access_token),
                    has_installation_id=bool(installation_id),
                    has_user_id=bool(user_id),
                    integration="vercel",
                )
                return OAuthTokenResponse(
                    access_token="",
                    token_type="",
                    installation_id="",
                    user_id="",
                    error="invalid_response",
                    error_description="Missing required fields in OAuth response",
                )

            return OAuthTokenResponse(
                access_token=access_token,
                token_type=token_type or "Bearer",
                installation_id=installation_id,
                user_id=user_id,
                team_id=json_data.get("team_id"),
            )
        except APIError as e:
            logger.exception("OAuth token exchange failed", error=str(e), integration="vercel")
            return OAuthTokenResponse(
                access_token="",
                token_type="",
                installation_id="",
                user_id="",
                error="exchange_failed",
                error_description=str(e),
            )

    @retry(
        stop=stop_after_attempt(INSTALLATION_TOKEN_ATTEMPTS),
        wait=wait_fixed(0.5),
        retry=retry_if_exception(lambda exc: isinstance(exc, InstallationTokenError) and exc.is_transient),
        reraise=True,
    )
    def request_installation_token(self, installation_id: str, client_id: str, client_secret: str) -> InstallationToken:
        try:
            response = self._request(
                "POST",
                VERCEL_OAUTH_TOKEN_URL,
                installation_id=installation_id,
                data=urlencode({"grant_type": "client_credentials", "installation_id": installation_id}),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                auth=(client_id, client_secret),
            )
            json_data = self._parse_json_response(response)
        except APIError as e:
            raise InstallationTokenError(
                e.message, status_code=e.status_code, detail=e.detail, code=_token_error_code(e.detail)
            ) from e

        access_token = json_data.get("access_token")
        expires_in = json_data.get("expires_in")
        if not access_token or not isinstance(expires_in, int):
            raise InstallationTokenError("Invalid token response", code="invalid_response")
        return InstallationToken(access_token=access_token, expires_in=expires_in)

    def get_installation_account(self, installation_id: str) -> dict[str, Any]:
        response = self._request(
            "GET", f"{self.base_url}/installations/{installation_id}/account", installation_id=installation_id
        )
        return self._parse_json_response(response)

    def check_installation_active(self, installation_id: str) -> bool:
        """Check if a Vercel installation is still active.

        Returns True if the installation exists and is accessible, False if
        Vercel returns 401/403/404 (meaning it's been removed). Raises on
        transient errors (5xx / network) so callers can distinguish
        "definitely gone" from "can't tell".
        """
        try:
            self._request("GET", f"{self.base_url}/installations/{installation_id}", installation_id=installation_id)
            return True
        except APIError as e:
            if e.status_code in (401, 403, 404):
                return False
            raise

    def sso_token_exchange(
        self,
        code: str,
        client_id: str,
        client_secret: str,
        state: str | None = None,
        redirect_uri: str | None = None,
        grant_type: str = "authorization_code",
    ) -> SSOTokenResponse | None:
        data = {"code": code, "client_id": client_id, "client_secret": client_secret, "grant_type": grant_type}
        if state:
            data["state"] = state
        if redirect_uri:
            data["redirect_uri"] = redirect_uri

        try:
            response = self._request(
                "POST",
                f"{self.base_url}/integrations/sso/token",
                installation_id=None,
                data=urlencode(data),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            json_data = self._parse_json_response(response)
            return self._validate_sso_response(json_data)
        except APIError as e:
            logger.exception("SSO token exchange failed", error=str(e), integration="vercel")

            return None


def _token_error_code(detail: str | None) -> str | None:
    try:
        error = json.loads(detail or "").get("error")
    except (json.JSONDecodeError, AttributeError):
        return None
    if isinstance(error, dict):
        return error.get("code")
    return error if isinstance(error, str) else None


def _read_cached_token(cache_key: str, installation_id: str) -> str | None:
    try:
        cached = token_cache.get(cache_key)
    except Exception:
        # The cache only saves a token request, so an outage costs a request, not the call.
        logger.warning("Vercel token cache read failed", installation_id=installation_id, integration="vercel")
        return None
    if not cached:
        return None
    try:
        return decrypt_payload(cached, salt=INSTALLATION_TOKEN_CACHE_SALT, ttl=INSTALLATION_TOKEN_MAX_AGE_SECONDS)[
            "access_token"
        ]
    except (InvalidToken, KeyError):
        # An entry from an earlier client secret; the next write replaces it.
        return None


def _acquire_token_lock(lock_key: str, installation_id: str) -> bool:
    try:
        return bool(token_cache.add(lock_key, True, timeout=INSTALLATION_TOKEN_LOCK_SECONDS))
    except Exception:
        logger.warning("Vercel token lock failed", installation_id=installation_id, integration="vercel")
        return True


def _release_token_lock(lock_key: str) -> None:
    try:
        token_cache.delete(lock_key)
    except Exception:
        pass  # The lock expires on its own.


def _wait_for_token_from_lock_holder(cache_key: str, lock_key: str, installation_id: str) -> str | None:
    for _ in range(INSTALLATION_TOKEN_LOCK_POLLS):
        time.sleep(INSTALLATION_TOKEN_LOCK_POLL_SECONDS)
        if token := _read_cached_token(cache_key, installation_id):
            return token
        try:
            if token_cache.get(lock_key) is None:
                return None  # The holder stopped without a token, so this caller requests its own.
        except Exception:
            return None
    return None


def get_installation_access_token(installation_id: str, *, fresh: bool = False) -> str:
    """Return a short-lived token for one Vercel installation, from the cache when it has time left.

    Callers that miss the cache together wait for one token request instead of each sending their own.
    ``fresh`` skips the cached token and the wait, for a caller that acts on a 401 or 403 from Vercel.
    """
    cache_key = f"{INSTALLATION_TOKEN_CACHE_PREFIX}{installation_id}"
    lock_key = f"{INSTALLATION_TOKEN_LOCK_PREFIX}{installation_id}"
    if not fresh:
        if cached_token := _read_cached_token(cache_key, installation_id):
            return cached_token

    client_id = settings.VERCEL_CLIENT_INTEGRATION_ID
    client_secret = settings.VERCEL_CLIENT_INTEGRATION_SECRET
    if not client_id or not client_secret:
        raise InstallationTokenError("Vercel integration not configured", code="not_configured")

    holds_lock = fresh or _acquire_token_lock(lock_key, installation_id)
    if not holds_lock:
        if holder_token := _wait_for_token_from_lock_holder(cache_key, lock_key, installation_id):
            return holder_token

    try:
        token = VercelAPIClient(
            bearer_token=None, timeout=INSTALLATION_TOKEN_ATTEMPT_SECONDS, source="installation_token"
        ).request_installation_token(installation_id, client_id, client_secret)

        cache_timeout = (
            min(token.expires_in, INSTALLATION_TOKEN_MAX_AGE_SECONDS) - INSTALLATION_TOKEN_EXPIRY_MARGIN_SECONDS
        )
        if cache_timeout > 0:
            try:
                token_cache.set(
                    cache_key,
                    encrypt_payload(
                        {"access_token": token.access_token}, salt=INSTALLATION_TOKEN_CACHE_SALT, jti=False
                    ),
                    timeout=cache_timeout,
                )
            except Exception:
                logger.warning("Vercel token cache write failed", installation_id=installation_id, integration="vercel")
        return token.access_token
    finally:
        if holds_lock and not fresh:
            _release_token_lock(lock_key)
