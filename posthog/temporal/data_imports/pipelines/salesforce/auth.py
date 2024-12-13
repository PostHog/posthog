import requests
from django.conf import settings
from dlt.common.pendulum import pendulum
from dlt.sources.helpers.rest_client.auth import BearerTokenAuth


class SalseforceAuth(BearerTokenAuth):
    def __init__(self, refresh_token, access_token):
        self.parse_native_representation(access_token)
        self.refresh_token = refresh_token
        self.token_expiry: pendulum.DateTime = pendulum.now()

    def __call__(self, request):
        if self.token is None or self.is_token_expired():
            self.obtain_token()
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request

    def is_token_expired(self) -> bool:
        return pendulum.now() >= self.token_expiry

    def obtain_token(self) -> None:
        new_token = salesforce_refresh_access_token(self.refresh_token)
        self.parse_native_representation(new_token)
        self.token_expiry = pendulum.now().add(hours=1)


def salesforce_refresh_access_token(refresh_token: str) -> str:
    res = requests.post(
        "https://login.salesforce.com/services/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": settings.SALESFORCE_CONSUMER_KEY,
            "client_secret": settings.SALESFORCE_CONSUMER_SECRET,
            "refresh_token": refresh_token,
        },
    )

    if res.status_code != 200:
        err_message = res.json()["error_description"]
        raise Exception(err_message)

    return res.json()["access_token"]


def get_salesforce_access_token_from_code(code: str, redirect_uri: str) -> tuple[str, str]:
    res = requests.post(
        "https://login.salesforce.com/services/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": settings.SALESFORCE_CONSUMER_KEY,
            "client_secret": settings.SALESFORCE_CONSUMER_SECRET,
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )

    if res.status_code != 200:
        err_message = res.json()["error_description"]
        raise Exception(err_message)

    payload = res.json()

    return payload["access_token"], payload["refresh_token"]
