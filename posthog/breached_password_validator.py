from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.views.decorators.debug import sensitive_variables

import httpx
import requests
from pwned_passwords_django.api import PwnedPasswords
from pwned_passwords_django.validators import PwnedPasswordsValidator

from posthog.egress.pwned_passwords import pwned_passwords_request


class EgressPwnedPasswordsHTTPClient:
    """The sync HTTP client that pwned-passwords-django calls, sent through the egress transport."""

    def get(self, url: str, headers: dict[str, str], timeout: httpx.Timeout) -> requests.Response:
        return pwned_passwords_request(url, source="password_validation", headers=headers, timeout=timeout.read)


_pwned_passwords_api_client = PwnedPasswords(client=EgressPwnedPasswordsHTTPClient())


class BreachedPasswordValidator(PwnedPasswordsValidator):
    """
    Reject a password that appears in a Have I Been Pwned data breach.
    If the API fails, pwned-passwords-django checks only Django's common-password list.
    """

    def __init__(self) -> None:
        super().__init__(
            error_message="This password appeared in a known data breach. Choose a different password.",
            api_client=_pwned_passwords_api_client,
        )

    @sensitive_variables()
    def validate(self, password: str, user: AbstractBaseUser | None = None) -> None:
        if settings.PWNED_PASSWORDS_CHECK_ENABLED:
            super().validate(password, user)
