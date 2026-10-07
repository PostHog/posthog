from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.models.user import User

from ee.partners.stripe.api.provisioning import AUTH_CODE_CACHE_PREFIX
from ee.partners.stripe.api.provisioning.test.base import BASE_PATH, StripeProvisioningTestBase

URL = f"{BASE_PATH}/provisioning/account_requests"


def _account_request(email: str, **overrides) -> dict:
    body = {
        "id": "acctreq_test",
        "email": email,
        "scopes": ["query:read"],
        # Static, not now()+delta: @parameterized.expand builds the invalid-request cases at
        # collection time, so a relative expiry can lapse before a slow shard reaches them and
        # trip the "expired" check ahead of the field validation each case actually asserts.
        "expires_at": "2999-01-01T00:00:00+00:00",
        "orchestrator": {"type": "stripe", "stripe": {"account": "acct_test"}},
    }
    body.update(overrides)
    return body


class TestAccountRequests(StripeProvisioningTestBase):
    def test_new_user_gets_auth_code_and_welcome_email(self):
        with patch("ee.partners.stripe.api.provisioning.core.send_provisioning_welcome") as welcome:
            res = self._post_signed(URL, data=_account_request("brand-new@example.com"))
        assert res.status_code == 200
        body = res.json()
        assert body["id"] == "acctreq_test"
        assert body["type"] == "oauth"

        code_data = cache.get(f"{AUTH_CODE_CACHE_PREFIX}{body['oauth']['code']}")
        user = User.objects.get(email="brand-new@example.com")
        assert code_data["user_id"] == user.id
        assert code_data["partner_id"] == ""
        assert code_data["stripe_account_id"] == "acct_test"
        assert code_data["scopes"] == ["query:read"]
        assert code_data["issued_at"]
        welcome.delay.assert_called_once()
        assert welcome.delay.call_args[0][2] == "Stripe"

    def test_existing_user_gets_silent_code_for_requested_team(self):
        res = self._post_signed(
            URL, data=_account_request(self.user.email, configuration={"region": "US", "team_id": self.team.id})
        )
        assert res.status_code == 200
        body = res.json()
        assert body["type"] == "oauth"
        code_data = cache.get(f"{AUTH_CODE_CACHE_PREFIX}{body['oauth']['code']}")
        assert code_data["user_id"] == self.user.id
        assert code_data["team_id"] == self.team.id

    def test_optional_fields_accept_explicit_null(self):
        # Spec JSON tolerance: an explicit null on an optional field is treated
        # as absent, not rejected with a 400.
        res = self._post_signed(
            URL,
            data=_account_request(
                self.user.email,
                id=None,
                scopes=None,
                confirmation_secret=None,
                expires_at=None,
                code_challenge=None,
                code_challenge_method=None,
                configuration=None,
            ),
        )
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"

    def test_wizard_configuration_block_is_ignored(self):
        res = self._post_signed(
            URL,
            data=_account_request(
                "wizardless@example.com",
                configuration={
                    "region": "US",
                    "wizard": {"grant_id": "g", "installation_id": "i", "repository": "o/r"},
                },
            ),
        )
        assert res.status_code == 200
        assert "wizard" not in res.json()

    def test_missing_signature_is_unauthorized(self):
        res = self.client.post(URL, data=_account_request("x@example.com"), format="json", HTTP_API_VERSION="0.1d")
        assert res.status_code == 401
        assert res.json() == {"type": "error", "error": {"code": "unauthorized", "message": "Authentication required"}}

    @parameterized.expand(
        [
            (
                "missing_email",
                _account_request(""),
                400,
                "invalid_request",
                "email is required",
            ),
            (
                "expired_request",
                _account_request("x@example.com", expires_at="2020-01-01T00:00:00+00:00"),
                400,
                "expired",
                "Account request has expired",
            ),
            (
                "expired_request_naive_timestamp",
                _account_request("x@example.com", expires_at="2020-01-01T00:00:00"),
                400,
                "expired",
                "Account request has expired",
            ),
            (
                "malformed_expires_at",
                _account_request("x@example.com", expires_at="not-a-date"),
                400,
                "invalid_request",
                "expires_at must be a valid ISO 8601 timestamp",
            ),
            (
                "out_of_range_expires_at",
                _account_request("x@example.com", expires_at="2020-13-01T00:00:00+00:00"),
                400,
                "invalid_request",
                "expires_at must be a valid ISO 8601 timestamp",
            ),
            (
                "missing_stripe_account",
                _account_request("x@example.com", orchestrator={"type": "stripe", "stripe": {}}),
                400,
                "invalid_request",
                "orchestrator.stripe.account is required",
            ),
            (
                "non_integer_team_id",
                _account_request("x@example.com", configuration={"team_id": "abc"}),
                400,
                "invalid_request",
                "configuration.team_id must be an integer",
            ),
            (
                "bad_code_challenge_method",
                _account_request("x@example.com", code_challenge="a" * 43, code_challenge_method="plain"),
                400,
                "invalid_request",
                "Only S256 code_challenge_method is supported",
            ),
            (
                "short_code_challenge",
                _account_request("x@example.com", code_challenge="short"),
                400,
                "invalid_request",
                "code_challenge must be 43-128 characters using base64url charset",
            ),
        ]
    )
    def test_invalid_requests_are_rejected(self, _name, body, status, code, message):
        res = self._post_signed(URL, data=body)
        assert res.status_code == status
        data = res.json()
        assert data["type"] == "error"
        assert data["error"] == {"code": code, "message": message}

    def test_missing_email_takes_priority_over_missing_signature(self):
        # Body validation runs before the signature requirement, so a request
        # that is both unsigned and missing the email reports the email error.
        res = self.client.post(URL, data={"id": "r1"}, format="json", HTTP_API_VERSION="0.1d")
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_request"
        assert res.json()["error"]["message"] == "email is required"
