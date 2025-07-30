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
