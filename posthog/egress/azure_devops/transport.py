import re
from typing import Any
from urllib.parse import quote

import requests
from prometheus_client import Counter
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

AZURE_DEVOPS_BASE_URL = "https://dev.azure.com"
AZURE_DEVOPS_API_VERSION = "7.1"
AZURE_DEVOPS_REQUEST_TIMEOUT_SECONDS = 60
AZURE_DEVOPS_MAX_RETRY_ATTEMPTS = 5

_ORGANIZATION_RE = re.compile(r"^[A-Za-z0-9._-]+$")

azure_devops_api_requests = Counter(
    "azure_devops_api_requests",
    "Number of Azure DevOps API requests made through the shared egress client.",
    labelnames=["method", "endpoint", "status_code", "source"],
)
azure_devops_api_exceptions = Counter(
    "azure_devops_api_exceptions",
    "Number of Azure DevOps API requests that failed before receiving a response.",
    labelnames=["method", "endpoint", "exception_type", "source"],
)


class AzureDevOpsRetryableError(Exception):
    def __init__(self, response: requests.Response) -> None:
        self.response = response
        super().__init__(f"Azure DevOps API returned retryable status {response.status_code}")


class AzureDevOpsAuthenticationError(Exception):
    pass


class AzureDevOpsUnexpectedRedirectError(Exception):
    pass


def normalize_azure_devops_identifier(value: str, name: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
        or any(ord(character) < 32 for character in normalized)
    ):
        raise ValueError(f"Invalid Azure DevOps {name}: {value!r}")
    return normalized


def normalize_azure_devops_organization(value: str) -> str:
    organization = value.strip().removeprefix("https://").removeprefix("http://")
    organization = organization.removeprefix("dev.azure.com/").split("/")[0]
    if not organization or not _ORGANIZATION_RE.fullmatch(organization) or organization in {".", ".."}:
        raise ValueError(f"Invalid Azure DevOps organization: {value!r}")
    return organization


class AzureDevOpsClient:
    """Shared Azure DevOps REST transport with PAT auth, telemetry, and safe retries."""

    def __init__(
        self,
        organization: str,
        personal_access_token: str,
        *,
        source: str,
        session: requests.Session | None = None,
        timeout: float = AZURE_DEVOPS_REQUEST_TIMEOUT_SECONDS,
        max_attempts: int = AZURE_DEVOPS_MAX_RETRY_ATTEMPTS,
    ) -> None:
        self.organization = normalize_azure_devops_organization(organization)
        self.personal_access_token = personal_access_token
        self.source = source
        self.session = session
        self.timeout = timeout
        self.max_attempts = max_attempts

    def request(
        self,
        method: str,
        path: str,
        *,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | list[dict[str, Any]] | None = None,
    ) -> requests.Response:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Azure DevOps request path must start with one slash")

        method = method.upper()

        def request() -> requests.Response:
            return self._request_once(method, path, endpoint=endpoint, params=params, json=json)

        if method not in {"GET", "HEAD", "OPTIONS"}:
            return request()

        retryer = Retrying(
            retry=retry_if_exception_type((AzureDevOpsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential_jitter(initial=2, max=120),
            reraise=True,
        )
        return retryer(request)

    def _request_once(
        self,
        method: str,
        path: str,
        *,
        endpoint: str,
        params: dict[str, Any] | None,
        json: dict[str, Any] | list[dict[str, Any]] | None,
    ) -> requests.Response:
        url = f"{AZURE_DEVOPS_BASE_URL}/{quote(self.organization)}{path}"
        query = {**(params or {}), "api-version": AZURE_DEVOPS_API_VERSION}
        sender = self.session or requests

        try:
            response = sender.request(
                method,
                url,
                params=query,
                json=json,
                auth=("", self.personal_access_token),
                allow_redirects=False,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            azure_devops_api_exceptions.labels(
                method=method,
                endpoint=endpoint,
                exception_type=type(error).__name__,
                source=self.source,
            ).inc()
            raise

        azure_devops_api_requests.labels(
            method=method,
            endpoint=endpoint,
            status_code=str(response.status_code),
            source=self.source,
        ).inc()

        if response.status_code == 203:
            raise AzureDevOpsAuthenticationError(
                "Azure DevOps returned a sign-in page (203); the personal access token is invalid or expired."
            )
        # Redirects are never followed (allow_redirects=False), so a 3xx body is not the JSON callers expect.
        if 300 <= response.status_code < 400:
            raise AzureDevOpsUnexpectedRedirectError(
                f"Azure DevOps returned an unexpected redirect (status {response.status_code})"
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise AzureDevOpsRetryableError(response)
        return response
