"""Google Ads integration."""

from typing import Any

from django.conf import settings

import requests
import structlog
from rest_framework.exceptions import APIException, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from posthog.egress.slack.client import SlackWebClient as WebClient
from posthog.exceptions_capture import capture_exception

from . import common, model

logger = structlog.get_logger(__name__)


def google_ads_hierarchy_level(account: dict) -> int:
    """Depth of an account below the manager the walk started from. Google's REST responses omit proto3
    defaults, so a level-0 account carries no `level` key at all, and deeper ones arrive as strings."""
    return int(account.get("level") or 0)


class GoogleAdsUnavailableError(Exception):
    """A transient Google Ads response we retry: 429 rate limit or 5xx server error."""

    def __init__(self, response: requests.Response) -> None:
        self.response = response
        super().__init__(f"Google Ads returned {response.status_code}")


class GoogleAdsTemporarilyUnavailable(APIException):
    # A transient 429/5xx from Google, still failing after retries, is not a client error. A 503 keeps
    # it in the 5xx class generic retry policies and monitoring key on, instead of the 400
    # validation_error a malformed request gets. As an APIException it is a handled error, so it does
    # not file an error-tracking issue.
    status_code = 503
    default_code = "google_ads_unavailable"
    default_detail = "Google Ads is temporarily unavailable. Try again in a moment."


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(
        (requests.exceptions.Timeout, requests.exceptions.ConnectionError, GoogleAdsUnavailableError)
    ),
    reraise=True,
)
def _google_ads_request(method: str, url: str, **kwargs) -> requests.Response:
    """`requests.request` with retries for a transient blip on Google's side.

    Retries a timeout, a connection error, and a 429 or 5xx response, all of which Google recovers
    from on its own. `list_google_ads_accessible_accounts` walks the account hierarchy with a chain
    of sequential requests, so a single transient blip on any one of them would otherwise fail the
    whole walk.
    """
    response = requests.request(method, url, **kwargs)
    if response.status_code == 429 or response.status_code >= 500:
        raise GoogleAdsUnavailableError(response)
    return response


class GoogleAdsIntegration:
    integration: model.Integration

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != "google-ads":
            raise Exception("GoogleAdsIntegration init called with Integration with wrong 'kind'")

        self.integration = integration

    @property
    def client(self) -> WebClient:
        return WebClient(self.integration.sensitive_config["access_token"])

    def list_google_ads_conversion_actions(self, customer_id, parent_id=None) -> list[dict]:
        try:
            response = _google_ads_request(
                "POST",
                f"https://googleads.googleapis.com/v24/customers/{customer_id}/googleAds:searchStream",
                json={
                    "query": "SELECT conversion_action.id, conversion_action.name FROM conversion_action WHERE conversion_action.status != 'REMOVED'"
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                    "developer-token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
                    **({"login-customer-id": parent_id} if parent_id else {}),
                },
                timeout=10,
            )
        except GoogleAdsUnavailableError as e:
            logger.warning(
                "GoogleAdsIntegration: Google Ads unavailable listing conversion actions",
                status_code=e.response.status_code,
                integration_id=self.integration.id,
            )
            raise GoogleAdsTemporarilyUnavailable()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            # _google_ads_request retries a timeout or connection error too, so reaching here means every
            # attempt failed to reach Google. It is transient like a 5xx, so surface the same 503 instead
            # of letting it reach the view as an unhandled 500. These exceptions carry no response, so log
            # the error text rather than a status code.
            logger.warning(
                "GoogleAdsIntegration: Google Ads unreachable listing conversion actions",
                error=str(e),
                integration_id=self.integration.id,
            )
            raise GoogleAdsTemporarilyUnavailable()

        if response.status_code == 401:
            logger.warning(
                "GoogleAdsIntegration: Auth error listing conversion actions",
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

        if response.status_code != 200:
            capture_exception(
                Exception(f"GoogleAdsIntegration: Failed to list ads conversion actions: {response.text}")
            )
            raise Exception("There was an internal error")

        return response.json()

    # Google Ads manager accounts can have access to other accounts (including other manager accounts).
    # Filter out duplicates where a user has direct access and access through a manager account, while prioritizing direct access.
    def list_google_ads_accessible_accounts(self) -> list[dict[str, Any]]:
        try:
            response = _google_ads_request(
                "GET",
                "https://googleads.googleapis.com/v24/customers:listAccessibleCustomers",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                    "developer-token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
                },
                timeout=10,
            )
        except GoogleAdsUnavailableError as e:
            logger.warning(
                "GoogleAdsIntegration: Google Ads unavailable listing accessible accounts",
                status_code=e.response.status_code,
                integration_id=self.integration.id,
            )
            raise GoogleAdsTemporarilyUnavailable()

        if response.status_code == 401:
            logger.warning(
                "GoogleAdsIntegration: Auth error listing accessible accounts",
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

        if response.status_code != 200:
            capture_exception(Exception(f"GoogleAdsIntegration: Failed to list accessible accounts: {response.text}"))
            raise Exception("There was an internal error")

        accessible_accounts = response.json()
        all_accounts: list[dict[str, Any]] = []

        def dfs(account_id, accounts=None, parent_id=None) -> list[dict]:
            if accounts is None:
                accounts = []
            try:
                response = _google_ads_request(
                    "POST",
                    f"https://googleads.googleapis.com/v24/customers/{account_id}/googleAds:searchStream",
                    json={
                        "query": "SELECT customer_client.descriptive_name, customer_client.client_customer, customer_client.level, customer_client.manager, customer_client.status FROM customer_client WHERE customer_client.level <= 5"
                    },
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                        "developer-token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
                        **({"login-customer-id": parent_id} if parent_id else {}),
                    },
                    timeout=10,
                )
            except GoogleAdsUnavailableError as e:
                # One branch failed after retries. Keep the accounts already collected rather than failing
                # the whole walk, but log the dropped branch so a short list is traceable to a transient
                # failure instead of looking complete.
                logger.warning(
                    "GoogleAdsIntegration: Google Ads unavailable walking account hierarchy",
                    status_code=e.response.status_code,
                    account_id=account_id,
                    integration_id=self.integration.id,
                )
                return accounts

            if response.status_code != 200:
                return accounts

            # searchStream's REST body is an array of response objects, one per streamed batch.
            data = response.json()
            results = [row for chunk in data for row in chunk.get("results", [])]

            for nested_account in results:
                client = nested_account["customerClient"]
                client_id = client["clientCustomer"].split("/")[1]
                # `level` is compared numerically: it is absent on the level-0 row and a string ("1", "2")
                # below it, so the raw values are not mutually comparable.
                client_level = google_ads_hierarchy_level(client)

                # Reject non-enabled accounts before deduping. Otherwise a disabled, shallower sighting
                # of an account we already kept as enabled would evict the enabled entry here and then be
                # skipped by the status check below, dropping the account from the picker entirely.
                if client.get("status") != "ENABLED":
                    continue

                # One account can be reached from several accessible roots — e.g. a user with access to
                # both a manager and one of its clients walks that client twice, once as a root (level 0)
                # and once beneath the manager (level 1). Keep the shallowest sighting, whose `parent_id`
                # is the account we can authenticate the sync as.
                already_seen = [account for account in accounts if account["id"] == client_id]
                if already_seen:
                    if all(google_ads_hierarchy_level(account) <= client_level for account in already_seen):
                        continue
                    accounts = [account for account in accounts if account["id"] != client_id]

                accounts.append(
                    {
                        "parent_id": parent_id,
                        "id": client_id,
                        "level": client.get("level"),
                        "name": client.get("descriptiveName", "Google Ads account"),
                        "manager": client.get("manager", False),
                    }
                )

            return accounts

        # A Google login with no accessible Ads accounts gets a 200 with an empty body, so
        # `resourceNames` is absent (proto3 omits empty repeated fields) rather than an empty list.
        for account in accessible_accounts.get("resourceNames", []):
            all_accounts = dfs(account.split("/")[1], all_accounts, account.split("/")[1])

        return all_accounts
