from django.conf import settings

import requests


def hubspot_refresh_access_token(refresh_token: str) -> str:
    res = requests.post(
        "https://api.hubapi.com/oauth/v1/token",
        data={
            "grant_type": "refresh_token",
            "client_id": settings.HUBSPOT_APP_CLIENT_ID,
            "client_secret": settings.HUBSPOT_APP_CLIENT_SECRET,
            "refresh_token": refresh_token,
        },
    )

    if res.status_code != 200:
        err_message = res.json()["message"]
        raise Exception(err_message)

    return res.json()["access_token"]


def get_hubspot_access_token_from_code(code: str, redirect_uri: str) -> tuple[str, str]:
    res = requests.post(
        "https://api.hubapi.com/oauth/v1/token",
        data={
            "grant_type": "authorization_code",
            "client_id": settings.HUBSPOT_APP_CLIENT_ID,
            "client_secret": settings.HUBSPOT_APP_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )

    if res.status_code != 200:
        err_message = res.json()["message"]
        raise Exception(err_message)

    payload = res.json()

    return payload["access_token"], payload["refresh_token"]
