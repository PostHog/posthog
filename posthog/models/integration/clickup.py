"""ClickUp integration."""

import requests
import structlog
from rest_framework.exceptions import ValidationError

from posthog.exceptions_capture import capture_exception

from . import common, model

logger = structlog.get_logger(__name__)


class ClickUpIntegration:
    integration: model.Integration

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != "clickup":
            raise Exception("ClickUpIntegration init called with Integration with wrong 'kind'")

        self.integration = integration

    def _check_auth_error(self, response: requests.Response, context: str) -> None:
        if response.status_code == 401:
            logger.warning(
                f"ClickUpIntegration: Auth error {context}",
                status_code=response.status_code,
                integration_id=self.integration.id,
            )
            self.integration.errors = common.ERROR_TOKEN_REFRESH_FAILED
            self.integration.save(update_fields=["errors"])
            raise ValidationError(
                "This integration's authentication is no longer valid. "
                "Please reconnect or disconnect this integration and connect a different account."
            )
        if response.status_code == 403:
            raise ValidationError(
                "This integration does not have permission to access this resource. "
                "Please check the account permissions on the provider side."
            )

    def list_clickup_spaces(self, workspace_id):
        response = requests.request(
            "GET",
            f"https://api.clickup.com/api/v2/team/{workspace_id}/space",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
            },
            timeout=10,
        )

        self._check_auth_error(response, "listing spaces")
        if response.status_code != 200:
            capture_exception(Exception(f"ClickUpIntegration: Failed to list spaces: {response.text}"))
            raise Exception("There was an internal error")

        return response.json()

    def list_clickup_folderless_lists(self, space_id):
        response = requests.request(
            "GET",
            f"https://api.clickup.com/api/v2/space/{space_id}/list",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
            },
            timeout=10,
        )

        self._check_auth_error(response, "listing lists")
        if response.status_code != 200:
            capture_exception(Exception(f"ClickUpIntegration: Failed to list lists: {response.text}"))
            raise Exception("There was an internal error")

        return response.json()

    def list_clickup_folders(self, space_id):
        response = requests.request(
            "GET",
            f"https://api.clickup.com/api/v2/space/{space_id}/folder",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
            },
            timeout=10,
        )

        self._check_auth_error(response, "listing folders")
        if response.status_code != 200:
            capture_exception(Exception(f"ClickUpIntegration: Failed to list folders: {response.text}"))
            raise Exception("There was an internal error")

        return response.json()

    def list_clickup_workspaces(self) -> dict:
        response = requests.request(
            "GET",
            "https://api.clickup.com/api/v2/team",
            headers={"Authorization": f"Bearer {self.integration.sensitive_config['access_token']}"},
            timeout=10,
        )

        self._check_auth_error(response, "listing workspaces")
        if response.status_code != 200:
            capture_exception(Exception(f"ClickUpIntegration: Failed to list workspaces: {response.text}"))
            raise Exception("There was an internal error")

        return response.json()
