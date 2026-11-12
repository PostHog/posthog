import hashlib

from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

from posthog.auth import BreachedPasswordValidator

PASSWORD = "vX9#qLm2$rTp-unique"
PASSWORD_SHA1 = hashlib.sha1(PASSWORD.encode()).hexdigest().upper()


def _range_response(status_code: int, body: str = "") -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = body.encode()
    return response


@override_settings(PWNED_PASSWORDS_CHECK_ENABLED=True)
class TestBreachedPasswordValidator(SimpleTestCase):
    def test_rejects_a_password_found_in_a_breach(self) -> None:
        body = f"0018A45C4D1DEF81644B54AB7F969B88D65:1\r\n{PASSWORD_SHA1[5:]}:3\r\n"

        with patch("requests.request", return_value=_range_response(200, body)) as request:
            with self.assertRaises(ValidationError) as error:
                BreachedPasswordValidator().validate(PASSWORD)

        assert error.exception.code == "password_compromised"
        assert error.exception.messages == [
            "This password appeared in a known data breach. Choose a different password."
        ]
        assert request.call_args.args[1] == f"https://api.pwnedpasswords.com/range/{PASSWORD_SHA1[:5]}"
        assert request.call_args.kwargs["timeout"] == 1.0

    def test_accepts_a_password_absent_from_the_range(self) -> None:
        with patch("requests.request", return_value=_range_response(200, "0018A45C4D1DEF81644B54AB7F969B88D65:1")):
            BreachedPasswordValidator().validate(PASSWORD)

    @parameterized.expand(
        [
            ("timeout", requests.Timeout("read timed out")),
            ("connection_error", requests.ConnectionError("connection refused")),
            ("server_error", None),
        ]
    )
    def test_accepts_the_password_when_the_api_fails(self, _name: str, error: Exception | None) -> None:
        with patch("requests.request", return_value=_range_response(503), side_effect=error):
            BreachedPasswordValidator().validate(PASSWORD)

    @override_settings(PWNED_PASSWORDS_CHECK_ENABLED=False)
    def test_makes_no_request_when_the_check_is_off(self) -> None:
        with patch("requests.request") as request:
            BreachedPasswordValidator().validate(PASSWORD)

        request.assert_not_called()
