from typing import Any
import requests
import structlog

logger = structlog.get_logger(__name__)


class VercelAPIClient:
    BASE_URL = "https://api.vercel.com/v1"

    def __init__(self, bearer_token: str):
        """
        Initialize Vercel API client.

        Args:
            bearer_token: The access token provided in the credentials field of the request body
                         of the Upsert Installation call. It is stored in the OrganizationIntegration model.
        """
        if not bearer_token:
            raise ValueError("Bearer token is required")

        self.bearer_token = bearer_token
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {bearer_token}"})

    def create_experimentation_items(
        self, integration_config_id: str, resource_id: str, items: list[dict[str, Any]]
    ) -> bool:
        url = f"{self.BASE_URL}/installations/{integration_config_id}/resources/{resource_id}/experimentation/items"

        try:
            response = self.session.post(url, json={"items": items})
            response.raise_for_status()
            logger.info(
                "Successfully created Vercel experimentation items",
                integration_config_id=integration_config_id,
                resource_id=resource_id,
                item_count=len(items),
            )
            return True
        except Exception:
            logger.exception(
                "Error occurred while creating Vercel experimentation items",
                integration_config_id=integration_config_id,
                resource_id=resource_id,
                status_code=getattr(response, "status_code", None),
                response_text=getattr(response, "text", None),
            )
            return False

    def update_experimentation_item(
        self, integration_config_id: str, resource_id: str, item_id: str, data: dict[str, Any]
    ) -> bool:
        url = f"{self.BASE_URL}/installations/{integration_config_id}/resources/{resource_id}/experimentation/items/{item_id}"

        try:
            response = self.session.patch(url, json=data)
            response.raise_for_status()
            logger.info(
                "Successfully updated Vercel experimentation item",
                integration_config_id=integration_config_id,
                resource_id=resource_id,
                item_id=item_id,
            )
            return True
        except Exception:
            logger.exception(
                "Error occurred while updating Vercel experimentation item",
                integration_config_id=integration_config_id,
                resource_id=resource_id,
                item_id=item_id,
                status_code=getattr(response, "status_code", None),
                response_text=getattr(response, "text", None),
            )
            return False

    def delete_experimentation_item(self, integration_config_id: str, resource_id: str, item_id: str) -> bool:
        url = f"{self.BASE_URL}/installations/{integration_config_id}/resources/{resource_id}/experimentation/items/{item_id}"

        try:
            response = self.session.delete(url)
            response.raise_for_status()
            logger.info(
                "Successfully deleted Vercel experimentation item",
                integration_config_id=integration_config_id,
                resource_id=resource_id,
                item_id=item_id,
            )
            return True
        except Exception:
            logger.exception(
                "Error occurred while deleting Vercel experimentation item",
                integration_config_id=integration_config_id,
                resource_id=resource_id,
                item_id=item_id,
                status_code=getattr(response, "status_code", None),
                response_text=getattr(response, "text", None),
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
            headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}
            response = self.session.post(url, data=data, headers=headers)
            response.raise_for_status()
            logger.info(
                "Successfully exchanged Vercel SSO token",
                client_id=client_id,
                has_state=state is not None,
            )
            return response.json()
        except Exception:
            logger.exception(
                "Error occurred while exchanging Vercel SSO token",
                client_id=client_id,
                status_code=getattr(response, "status_code", None),
                response_text=getattr(response, "text", None),
            )
            return None
