import json
from typing import Any, NotRequired, Required, TypedDict, cast
from urllib.parse import urlencode

import requests
import structlog
from requests import HTTPError, RequestException, Timeout

logger = structlog.get_logger(__name__)


class SSOTokenResponse(TypedDict):
    access_token: Required[str]
    token_type: Required[str]
    id_token: NotRequired[str]
    expires_in: NotRequired[int]
    scope: NotRequired[str]
    refresh_token: NotRequired[str]
    error: NotRequired[str]
    error_description: NotRequired[str]


class ExperimentationResult(TypedDict):
    success: bool
    item_id: NotRequired[str]
    item_count: NotRequired[int]
    error: NotRequired[str]
    status_code: NotRequired[int]
    error_detail: NotRequired[str]


class VercelAPIClient:
    def __init__(self, bearer_token: str, timeout: int = 30, base_url: str = "https://api.vercel.com/v1"):
        if not bearer_token or not bearer_token.strip():
            raise ValueError("Bearer token is required")

        self.bearer_token = bearer_token
        self.timeout = timeout
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {bearer_token}"})

    def _get_status_code_from_exception(self, exc: Exception) -> int | None:
        if isinstance(exc, HTTPError) and hasattr(exc, "response") and exc.response:
            return exc.response.status_code
        return None

    def _request(
        self, method: str, url: str, operation_name: str, **kwargs
    ) -> tuple[requests.Response | None, dict[str, Any]]:
        try:
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
            response.raise_for_status()
            return response, {}
        except Timeout:
            logger.exception(f"Timeout occurred during {operation_name}", method=method, url=url)
            return None, {"error": "Request timed out", "error_detail": "The request exceeded the configured timeout"}
        except HTTPError as e:
            status_code = self._get_status_code_from_exception(e)
            error_detail = getattr(e.response, "text", "") if hasattr(e, "response") and e.response else ""
            logger.exception(
                f"HTTP error occurred during {operation_name}",
                method=method,
                url=url,
                status_code=status_code,
            )
            result = {
                "error": "HTTP error",
                "error_detail": error_detail[:200] if error_detail else f"HTTP {status_code or 0} error",
            }
            if status_code is not None:
                result["status_code"] = status_code
            return None, result
        except RequestException as e:
            logger.exception(f"Network error occurred during {operation_name}", method=method, url=url)
            return None, {"error": "Network error", "error_detail": str(e)[:200]}
        except Exception as e:
            logger.exception(f"Unexpected error occurred during {operation_name}", method=method, url=url)
            return None, {"error": "Unexpected error", "error_detail": str(e)[:200]}

    def create_experimentation_items(
        self, integration_config_id: str, resource_id: str, items: list[dict[str, Any]]
    ) -> ExperimentationResult:
        if not items:
            raise ValueError("items list cannot be empty")

        url = f"{self.base_url}/installations/{integration_config_id}/resources/{resource_id}/experimentation/items"

        response, error_info = self._request(
            "POST", url, "Vercel experimentation items creation", json={"items": items}
        )

        if response:
            logger.info(
                "Successfully created Vercel experimentation items",
                integration_config_id=integration_config_id,
                resource_id=resource_id,
                item_count=len(items),
            )
            return {"success": True, "item_count": len(items)}

        result: ExperimentationResult = {"success": False}
        result.update(cast(ExperimentationResult, error_info))
        return result

    def update_experimentation_item(
        self, integration_config_id: str, resource_id: str, item_id: str, data: dict[str, Any]
    ) -> ExperimentationResult:
        if not data:
            raise ValueError("data dictionary cannot be empty")

        url = f"{self.base_url}/installations/{integration_config_id}/resources/{resource_id}/experimentation/items/{item_id}"

        response, error_info = self._request("PATCH", url, "Vercel experimentation item update", json=data)

        if response:
            logger.info(
                "Successfully updated Vercel experimentation item",
                integration_config_id=integration_config_id,
                resource_id=resource_id,
                item_id=item_id,
            )
            return {"success": True, "item_id": item_id}

        result: ExperimentationResult = {"success": False}
        result.update(cast(ExperimentationResult, error_info))
        return result

    def delete_experimentation_item(
        self, integration_config_id: str, resource_id: str, item_id: str
    ) -> ExperimentationResult:
        url = f"{self.base_url}/installations/{integration_config_id}/resources/{resource_id}/experimentation/items/{item_id}"

        response, error_info = self._request("DELETE", url, "Vercel experimentation item deletion")

        if response:
            logger.info(
                "Successfully deleted Vercel experimentation item",
                integration_config_id=integration_config_id,
                resource_id=resource_id,
                item_id=item_id,
            )
            return {"success": True, "item_id": item_id}

        result: ExperimentationResult = {"success": False}
        result.update(cast(ExperimentationResult, error_info))
        return result

    def sso_token_exchange(
        self,
        code: str,
        client_id: str,
        client_secret: str,
        state: str | None = None,
        redirect_uri: str | None = None,
        grant_type: str = "authorization_code",
    ) -> SSOTokenResponse | None:
        url = f"{self.base_url}/integrations/sso/token"

        data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": grant_type,
        }

        if state is not None:
            data["state"] = state
        if redirect_uri is not None:
            data["redirect_uri"] = redirect_uri

        response, error_info = self._request(
            "POST",
            url,
            "Vercel SSO token exchange",
            data=urlencode(data),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response:
            logger.info("Successfully exchanged Vercel SSO token", has_state=state is not None)
            try:
                return response.json()
            except json.JSONDecodeError:
                logger.exception("Failed to parse JSON response during Vercel SSO token exchange")

        return None
