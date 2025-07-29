import requests
from django.conf import settings
from dlt.common.pendulum import pendulum
from dlt.sources.helpers.rest_client.auth import BearerTokenAuth


class SalesforceAuth(BearerTokenAuth):
    def __init__(self, refresh_token, access_token, instance_url):
        self.parse_native_representation(access_token)
        self.refresh_token = refresh_token
        self.token_expiry: pendulum.DateTime = pendulum.now()
        self.instance_url = instance_url

    def __call__(self, request):
        if self.token is None or self.is_token_expired():
            self.obtain_token()
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request

    def is_token_expired(self) -> bool:
        return pendulum.now() >= self.token_expiry

    def obtain_token(self) -> None:
        new_token = salesforce_refresh_access_token(self.refresh_token, self.instance_url)
        self.parse_native_representation(new_token)
        self.token_expiry = pendulum.now().add(hours=1)


class SalesforceAuthRequestError(Exception):
    """Exception to capture errors when an auth request fails."""

    def __init__(self, error_message: str, response: requests.Response):
        self.response = response
        super().__init__(error_message)

    @classmethod
    def raise_from_response(cls, response: requests.Response) -> None:
        """Raise a `SalesforceAuthRequestError` from a failed response.

        If the response did not fail, nothing is raised or returned.
        """
        if 400 <= response.status_code < 500:
            error_message = f"{response.status_code} Client Error: {response.reason}: "

        elif 500 <= response.status_code < 600:
            error_message = f"{response.status_code} Server Error: {response.reason}: "
        else:
            return

        try:
            error_description = response.json()["error_description"]
        except requests.exceptions.JSONDecodeError:
            if response.text:
                error_message += response.text
            else:
                error_message += "No additional error details"
        else:
            error_message += error_description

        raise cls(error_message, response=response)


def salesforce_refresh_access_token(refresh_token: str, instance_url: str) -> str:
    res = requests.post(
        f"{instance_url}/services/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": settings.SALESFORCE_CONSUMER_KEY,
            "client_secret": settings.SALESFORCE_CONSUMER_SECRET,
            "refresh_token": refresh_token,
        },
    )

    SalesforceAuthRequestError.raise_from_response(res)

    return res.json()["access_token"]


def get_salesforce_access_token_from_code(code: str, redirect_uri: str, instance_url: str) -> tuple[str, str]:
    res = requests.post(
        f"{instance_url}/services/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": settings.SALESFORCE_CONSUMER_KEY,
            "client_secret": settings.SALESFORCE_CONSUMER_SECRET,
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )

    SalesforceAuthRequestError.raise_from_response(res)

    payload = res.json()

    return payload["access_token"], payload["refresh_token"]
