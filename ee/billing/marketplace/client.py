import requests
import structlog

from posthog.models.organization_integration import OrganizationIntegration

logger = structlog.get_logger(__name__)

VERCEL_API_BASE_URL = "https://api.vercel.com"
REQUEST_TIMEOUT_SECONDS = 30


class MarketplaceClient:
    """
    HTTP client for marketplace API interactions.

    Handles authentication, URL construction, and request/response lifecycle.
    """

    def __init__(self, integration: OrganizationIntegration):
        self._integration = integration
        self._config_id = integration.integration_id
        self._access_token = self._extract_access_token(integration)

    def submit(self, endpoint_template: str, payload: dict) -> None:
        """Submit payload to marketplace API endpoint."""
        endpoint = endpoint_template.format(config_id=self._config_id)
        url = f"{VERCEL_API_BASE_URL}{endpoint}"

        response = requests.post(
            url,
            headers=self._build_headers(),
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        self._handle_response(response, endpoint)

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def _handle_response(self, response: requests.Response, endpoint: str) -> None:
        if not response.ok:
            logger.error(
                "Marketplace API request failed",
                status_code=response.status_code,
                response_text=response.text[:500],
                config_id=self._config_id,
                endpoint=endpoint,
            )
            response.raise_for_status()

        logger.info(
            "Marketplace API request succeeded",
            config_id=self._config_id,
            endpoint=endpoint,
        )

    @staticmethod
    def _extract_access_token(integration: OrganizationIntegration) -> str:
        token = integration.config.get("credentials", {}).get("access_token")
        if not token:
            raise ValueError(f"No access token found for integration {integration.integration_id}")
        return token
