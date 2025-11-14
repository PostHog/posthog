"""Zoho CRM OAuth authentication helpers"""

from django.conf import settings

import requests


def zoho_crm_refresh_access_token(refresh_token: str, api_domain: str) -> str:
    """
    Refresh the Zoho CRM access token using the refresh token.

    Args:
        refresh_token: The OAuth refresh token
        api_domain: The Zoho API domain (e.g., https://accounts.zoho.com)

    Returns:
        The new access token

    Raises:
        ValueError: If token refresh fails
    """
    token_url = f"{api_domain}/oauth/v2/token"

    data = {
        "refresh_token": refresh_token,
        "client_id": settings.ZOHO_CRM_CLIENT_ID,
        "client_secret": settings.ZOHO_CRM_CLIENT_SECRET,
        "grant_type": "refresh_token",
    }

    response = requests.post(token_url, data=data)

    if response.status_code != 200:
        raise ValueError(f"Failed to refresh Zoho CRM access token: {response.text}")

    response_data = response.json()

    if "access_token" not in response_data:
        raise ValueError(f"No access token in Zoho CRM refresh response: {response_data}")

    return response_data["access_token"]
