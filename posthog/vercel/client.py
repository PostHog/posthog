from typing import Any
import requests
import structlog

logger = structlog.get_logger(__name__)


class VercelAPIClient:
    """Client for making requests to Vercel API"""

    BASE_URL = "https://api.vercel.com/v1"

    def __init__(self, bearer_token: str = "mock_token"):
        self.bearer_token = bearer_token
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {bearer_token}", "Content-Type": "application/json"})

    def create_experimentation_items(
        self, integration_config_id: str, resource_id: str, items: list[dict[str, Any]]
    ) -> bool:
        """
        Create one or multiple experimentation items
        """
        url = f"{self.BASE_URL}/installations/{integration_config_id}/resources/{resource_id}/experimentation/items"

        try:
            response = self.session.post(url, json={"items": items})
            if response.status_code == 204:
                logger.info(
                    "vercel_experimentation_items_created",
                    integration_config_id=integration_config_id,
                    resource_id=resource_id,
                    item_count=len(items),
                )
                return True
            else:
                logger.error(
                    "vercel_experimentation_items_create_failed",
                    integration_config_id=integration_config_id,
                    resource_id=resource_id,
                    status_code=response.status_code,
                    response_text=response.text,
                )
                return False
        except Exception as e:
            logger.exception(
                "vercel_experimentation_items_create_error",
                integration_config_id=integration_config_id,
                resource_id=resource_id,
                error=str(e),
            )
            return False

    def update_experimentation_item(
        self, integration_config_id: str, resource_id: str, item_id: str, data: dict[str, Any]
    ) -> bool:
        """
        Update an existing experimentation item
        """
        url = f"{self.BASE_URL}/installations/{integration_config_id}/resources/{resource_id}/experimentation/items/{item_id}"

        try:
            response = self.session.patch(url, json=data)
            if response.status_code == 204:
                logger.info(
                    "vercel_experimentation_item_updated",
                    integration_config_id=integration_config_id,
                    resource_id=resource_id,
                    item_id=item_id,
                )
                return True
            else:
                logger.error(
                    "vercel_experimentation_item_update_failed",
                    integration_config_id=integration_config_id,
                    resource_id=resource_id,
                    item_id=item_id,
                    status_code=response.status_code,
                    response_text=response.text,
                )
                return False
        except Exception as e:
            logger.exception(
                "vercel_experimentation_item_update_error",
                integration_config_id=integration_config_id,
                resource_id=resource_id,
                item_id=item_id,
                error=str(e),
            )
            return False

    def delete_experimentation_item(self, integration_config_id: str, resource_id: str, item_id: str) -> bool:
        """Delete an existing experimentation item"""
        url = f"{self.BASE_URL}/installations/{integration_config_id}/resources/{resource_id}/experimentation/items/{item_id}"

        try:
            response = self.session.delete(url)
            if response.status_code == 204:
                logger.info(
                    "vercel_experimentation_item_deleted",
                    integration_config_id=integration_config_id,
                    resource_id=resource_id,
                    item_id=item_id,
                )
                return True
            else:
                logger.error(
                    "vercel_experimentation_item_delete_failed",
                    integration_config_id=integration_config_id,
                    resource_id=resource_id,
                    item_id=item_id,
                    status_code=response.status_code,
                    response_text=response.text,
                )
                return False
        except Exception as e:
            logger.exception(
                "vercel_experimentation_item_delete_error",
                integration_config_id=integration_config_id,
                resource_id=resource_id,
                item_id=item_id,
                error=str(e),
            )
            return False

    def sso_token_exchange(
        self,
        code: str,
        client_id: str,
        client_secret: str,
        state: str | None = None,
        redirect_uri: str | None = None,
        grant_type: str = "authorization_code",
    ) -> dict[str, Any] | None:
        """
        Exchange authorization code for OIDC token during SSO flow
        """
        url = f"{self.BASE_URL}/integrations/sso/token"

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

        try:
            # Use form-encoded content type for token exchange
            headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}
            response = self.session.post(url, data=data, headers=headers)

            if response.status_code == 200:
                logger.info(
                    "vercel_sso_token_exchange_success",
                    client_id=client_id,
                    has_state=state is not None,
                )
                return response.json()
            else:
                logger.error(
                    "vercel_sso_token_exchange_failed",
                    client_id=client_id,
                    status_code=response.status_code,
                    response_text=response.text,
                )
                return None
        except Exception as e:
            logger.exception(
                "vercel_sso_token_exchange_error",
                client_id=client_id,
                error=str(e),
            )
            return None
