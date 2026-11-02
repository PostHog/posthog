from contextlib import AbstractContextManager, nullcontext
from typing import Any

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import IntegrityError
from django.test import override_settings

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.organization_provisioning import OrganizationProvisioning
from posthog.models.user import User

from ee.partners.stripe.api.provisioning import AUTH_CODE_CACHE_PREFIX
from ee.partners.stripe.api.provisioning.core import ACCOUNT_NOT_LINKABLE_MESSAGE, EMAIL_NOT_VERIFIED_MESSAGE
from ee.partners.stripe.api.provisioning.test.base import BASE_PATH, StripeProvisioningTestBase

URL = f"{BASE_PATH}/provisioning/account_requests"
CAPTURE = "ee.partners.stripe.api.provisioning.analytics.posthoganalytics.capture"


def _account_request_events(capture: MagicMock) -> list[dict[str, Any]]:
    return [
        call.kwargs["properties"]
        for call in capture.call_args_list
        if call.args[:1] == ("agentic_provisioning account_request",)
    ]


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
    @parameterized.expand(
        [
            ("without_kyc", {}),
            ("with_malformed_kyc", {"kyc": "email"}),
        ]
    )
    def test_new_user_gets_auth_code_and_welcome_email(self, _name: str, kyc_fields: dict[str, Any]) -> None:
        with patch("ee.partners.stripe.api.provisioning.core.send_provisioning_welcome") as welcome:
            res = self._post_signed(URL, data=_account_request("brand-new@example.com", **kyc_fields))
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

    def test_only_the_organization_created_for_a_new_user_is_recorded_as_stripe_created(self):
        self._post_signed(URL, data=_account_request(self.user.email))
        self._post_signed(URL, data=_account_request("brand-new@example.com"))

        new_organization = User.objects.get(email="brand-new@example.com").organization
        assert new_organization is not None
        assert list(OrganizationProvisioning.objects.values_list("organization_id", "partner", "application_id")) == [
            (new_organization.id, "stripe_projects", self.stripe_app.id)
        ]

    @parameterized.expand(
        [
            ("without_the_stripe_app", override_settings(STRIPE_POSTHOG_OAUTH_CLIENT_ID=""), "server_error"),
            (
                "when_recording_the_organization_partner_fails",
                patch(
                    "ee.partners.stripe.api.provisioning.core.OrganizationProvisioning.objects.create",
                    side_effect=IntegrityError,
                ),
                "account_creation_failed",
            ),
        ]
    )
    def test_new_user_is_not_created(
        self, _name: str, failure: AbstractContextManager[object], error_code: str
    ) -> None:
        organization_count = Organization.objects.count()

        with failure:
            res = self._post_signed(URL, data=_account_request("brand-new@example.com"))

        assert res.status_code == 500
        assert res.json()["error"]["code"] == error_code
        assert not User.objects.filter(email="brand-new@example.com").exists()
        assert Organization.objects.count() == organization_count

    @parameterized.expand(
        [
            ("without_kyc", {}, None),
            ("with_verified_email", {"kyc": {"verified_fields": ["name", "email"]}}, True),
        ]
    )
    def test_existing_user_gets_silent_code_for_requested_team(
        self, _name: str, kyc_fields: dict[str, Any], kyc_email_verified: bool | None
    ) -> None:
        with patch(CAPTURE) as capture:
            res = self._post_signed(
                URL,
                data=_account_request(
                    self.user.email, configuration={"region": "US", "team_id": self.team.id}, **kyc_fields
                ),
            )
        assert res.status_code == 200
        body = res.json()
        assert body["type"] == "oauth"
        code_data = cache.get(f"{AUTH_CODE_CACHE_PREFIX}{body['oauth']['code']}")
        assert code_data["user_id"] == self.user.id
        assert code_data["team_id"] == self.team.id
        assert [(event["outcome"], event["kyc_email_verified"]) for event in _account_request_events(capture)] == [
            ("existing_user", kyc_email_verified)
        ]

    @parameterized.expand(
        [
            (
                "kyc_without_email",
                {"verified_fields": ["name", "phone"]},
                True,
                False,
                "requires_kyc",
                EMAIL_NOT_VERIFIED_MESSAGE,
                ["email_not_verified"],
            ),
            (
                "kyc_without_verified_fields",
                {},
                True,
                False,
                "requires_kyc",
                EMAIL_NOT_VERIFIED_MESSAGE,
                ["email_not_verified"],
            ),
            (
                "kyc_with_verified_fields_not_a_list",
                {"verified_fields": "email"},
                True,
                False,
                "requires_kyc",
                EMAIL_NOT_VERIFIED_MESSAGE,
                ["email_not_verified"],
            ),
            (
                "deactivated_user",
                {"verified_fields": ["email"]},
                False,
                False,
                "forbidden",
                ACCOUNT_NOT_LINKABLE_MESSAGE,
                ["user_inactive"],
            ),
            (
                "concurrent_signup_with_kyc_without_email",
                {"verified_fields": ["name"]},
                True,
                True,
                "requires_kyc",
                EMAIL_NOT_VERIFIED_MESSAGE,
                ["race_condition_existing_user", "email_not_verified"],
            ),
        ]
    )
    def test_existing_user_is_not_linked(
        self,
        _name: str,
        kyc: Any,
        user_is_active: bool,
        concurrent_signup: bool,
        error_code: str,
        message: str,
        outcomes: list[str],
    ) -> None:
        self.user.is_active = user_is_active
        self.user.save()
        view_lookup_misses_user: AbstractContextManager[object] = (
            patch(
                "ee.partners.stripe.api.provisioning.views.EmailLookupHandler",
                MagicMock(**{"get_user_by_email.return_value": None}),
            )
            if concurrent_signup
            else nullcontext()
        )

        with (
            view_lookup_misses_user,
            patch("ee.partners.stripe.api.provisioning.core.cache") as auth_code_cache,
            patch(CAPTURE) as capture,
        ):
            res = self._post_signed(URL, data=_account_request(self.user.email, kyc=kyc))

        assert res.status_code == 403
        assert res.json() == {"id": "acctreq_test", "type": "error", "error": {"code": error_code, "message": message}}
        auth_code_cache.set.assert_not_called()
        assert [event["outcome"] for event in _account_request_events(capture)] == outcomes

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
                kyc=None,
            ),
        )
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"

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
