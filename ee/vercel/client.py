import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests
import structlog
from requests import HTTPError, RequestException, Timeout
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)


@dataclass
class SSOTokenResponse:
    access_token: str
    token_type: str
    id_token: str | None = None
    scope: str | None = None
    refresh_token: str | None = None
    error: str | None = None
    error_description: str | None = None


@dataclass
class APIError(Exception):
    message: str
    status_code: int | None = None
    detail: str | None = None

    def __str__(self) -> str:
        return f"{self.message} (status: {self.status_code})"


@dataclass
class ExperimentationResult:
    success: bool
    item_id: str | None = None
    item_count: int | None = None
    error: str | None = None
    status_code: int | None = None
    error_detail: str | None = None


class VercelAPIClient:
    def __init__(self, bearer_token: str | None, timeout: int = 30, base_url: str = "https://api.vercel.com/v1"):
        self.bearer_token = bearer_token
        self.timeout = timeout
        self.base_url = base_url
        self.session = requests.Session()

        # Not all endpoints (Such as SSO token exchange) require authorization
        if bearer_token and bearer_token.strip():
            headers = {
                "Authorization": f"Bearer {bearer_token}",
                "Content-Type": "application/json",
            }
            self.session.headers.update(headers)

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
        success_msg: str,
        log_kwargs: dict[str, Any],
        result_kwargs: dict[str, Any],
        **request_kwargs,
    ) -> ExperimentationResult:
        try:
            self._request(method, url, **request_kwargs)
            logger.info(success_msg, integration="vercel", **log_kwargs)
            return ExperimentationResult(success=True, **result_kwargs)
        except APIError as e:
            return ExperimentationResult(
                success=False, error=e.message, status_code=e.status_code, error_detail=e.detail
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(lambda exc: VercelAPIClient._should_retry_request(exc)),
    )
    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        try:
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
            response.raise_for_status()
            return response
        except Timeout as e:
            logger.exception("Request timeout", method=method, url=url, integration="vercel")
            raise APIError("Request timed out", detail=str(e))
        except HTTPError as e:
            status_code = e.response.status_code if e.response else None
            detail = e.response.text if e.response else str(e)
            logger.exception("HTTP error", method=method, url=url, status_code=status_code, integration="vercel")
            raise APIError("HTTP error", status_code=status_code, detail=detail)
        except RequestException as e:
            logger.exception("Network error", method=method, url=url, integration="vercel")
            raise APIError("Network error", detail=str(e))

    def create_experimentation_items(
        self, integration_config_id: str, resource_id: str, items: list[dict[str, Any]]
    ) -> ExperimentationResult:
        if not items:
            raise ValueError("items list cannot be empty")

        url = f"{self.base_url}/installations/{integration_config_id}/resources/{resource_id}/experimentation/items"
        return self._crud_operation(
            "POST",
            url,
            "Successfully created experimentation items",
            {"integration_config_id": integration_config_id, "resource_id": resource_id, "item_count": len(items)},
            {"item_count": len(items)},
            json={"items": items},
        )

    def update_experimentation_item(
        self, integration_config_id: str, resource_id: str, item_id: str, data: dict[str, Any]
    ) -> ExperimentationResult:
        if not data:
            raise ValueError("data dictionary cannot be empty")

        url = f"{self.base_url}/installations/{integration_config_id}/resources/{resource_id}/experimentation/items/{item_id}"
        return self._crud_operation(
            "PATCH",
            url,
            "Successfully updated experimentation item",
            {"integration_config_id": integration_config_id, "resource_id": resource_id, "item_id": item_id},
            {"item_id": item_id},
            json=data,
        )

    def delete_experimentation_item(
        self, integration_config_id: str, resource_id: str, item_id: str
    ) -> ExperimentationResult:
        url = f"{self.base_url}/installations/{integration_config_id}/resources/{resource_id}/experimentation/items/{item_id}"
        return self._crud_operation(
            "DELETE",
            url,
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
                data=urlencode(data),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            json_data = self._parse_json_response(response)
            return self._validate_sso_response(json_data)
        except APIError as e:
            logger.exception("SSO token exchange failed", error=str(e), integration="vercel")

            return None
