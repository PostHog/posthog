from enum import Enum
from typing import Optional, Any
from collections.abc import Iterator
from dlt.common.typing import DictStrStr, TDataItems, TSecretValue
from dlt.sources.helpers.requests import client

from . import settings
from .credentials import (
    ZendeskCredentialsEmailPass,
    ZendeskCredentialsOAuth,
    ZendeskCredentialsToken,
    TZendeskCredentials,
)


class PaginationType(Enum):
    OFFSET = 0
    CURSOR = 1
    STREAM = 2
    START_TIME = 3


class ZendeskAPIClient:
    """
    API client used to make requests to Zendesk talk, support and chat API
    """

    subdomain: str = ""
    url: str = ""
    headers: Optional[DictStrStr]
    auth: Optional[tuple[str, TSecretValue]]

    def __init__(self, credentials: TZendeskCredentials, url_prefix: Optional[str] = None) -> None:
        """
        Initializer for the API client which is then used to make API calls to the ZendeskAPI

        Args:
            credentials: ZendeskCredentials object which contains the necessary credentials to authenticate to ZendeskAPI
        """
        # oauth token is the preferred way to authenticate, followed by api token and then email + password combo
        # fill headers and auth for every possibility of credentials given, raise error if credentials are of incorrect type
        if isinstance(credentials, ZendeskCredentialsOAuth):
            self.headers = {"Authorization": f"Bearer {credentials.oauth_token}"}
            self.auth = None
        elif isinstance(credentials, ZendeskCredentialsToken):
            self.headers = None
            self.auth = (f"{credentials.email}/token", credentials.token)
        elif isinstance(credentials, ZendeskCredentialsEmailPass):
            self.auth = (credentials.email, credentials.password)
            self.headers = None
        else:
            raise TypeError(
                "Wrong credentials type provided to ZendeskAPIClient. The credentials need to be of type: ZendeskCredentialsOAuth, ZendeskCredentialsToken or ZendeskCredentialsEmailPass"
            )

        # If url_prefix is set it overrides the default API URL (e.g. chat api uses zopim.com domain)
        if url_prefix:
            self.url = url_prefix
        else:
            self.subdomain = credentials.subdomain
            self.url = f"https://{self.subdomain}.zendesk.com"

    def get_pages(
        self,
        endpoint: str,
        data_point_name: str,
        pagination: PaginationType,
        params: Optional[dict[str, Any]] = None,
    ) -> Iterator[TDataItems]:
        """
        Makes a request to a paginated endpoint and returns a generator of data items per page.

        Args:
            endpoint: The url to the endpoint, e.g. /api/v2/calls
            data_point_name: The key which data items are nested under in the response object (e.g. calls)
            params: Optional dict of query params to include in the request
            pagination: Type of pagination type used by endpoint

        Returns:
            Generator of pages, each page is a list of dict data items
        """

        # update the page size to enable cursor pagination
        params = params or {}
        if pagination == PaginationType.CURSOR:
            params["page[size]"] = settings.PAGE_SIZE
        elif pagination == PaginationType.STREAM:
            params["per_page"] = settings.INCREMENTAL_PAGE_SIZE
        elif pagination == PaginationType.START_TIME:
            params["limit"] = settings.INCREMENTAL_PAGE_SIZE

        # make request and keep looping until there is no next page
        get_url = f"{self.url}{endpoint}"
        while get_url:
            response = client.get(get_url, headers=self.headers, auth=self.auth, params=params)
            response.raise_for_status()
            response_json = response.json()
            result = response_json[data_point_name]
            yield result

            get_url = None
            if pagination == PaginationType.CURSOR:
                if response_json["meta"]["has_more"]:
                    get_url = response_json["links"]["next"]
            elif pagination == PaginationType.OFFSET:
                get_url = response_json.get("next_page", None)
            elif pagination == PaginationType.STREAM:
                # See https://developer.zendesk.com/api-reference/ticketing/ticket-management/incremental_exports/#json-format
                if not response_json["end_of_stream"]:
                    get_url = response_json["next_page"]
            elif pagination == PaginationType.START_TIME:
                if response_json["count"] > 0:
                    get_url = response_json["next_page"]

            params = {}
