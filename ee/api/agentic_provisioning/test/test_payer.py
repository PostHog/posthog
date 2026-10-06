import json
import time
import uuid
from typing import Any

from unittest.mock import patch

from django.conf import settings

import jwt
import requests
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized

from posthog.api.oauth.client_assertion import CLIENT_ASSERTION_TYPE_JWT_BEARER
from posthog.models.oauth import OAuthApplication
from posthog.token_bucket import Budget

from ee.api.agentic_provisioning.ratelimits import FLAT_MULTIPLIERS
from ee.api.agentic_provisioning.test.base import (
    TEST_PARTNER_SCOPES,
    ProvisioningTestBase,
    patched_budget,
    provisioning_config,
)
from ee.api.agentic_provisioning.views import PayerView
from ee.api.test.base import LicensedTestMixin
from ee.api.test.test_partner_billing import (
    BILLING_DETAIL,
    CUSTOMER_ORGANIZATION_ID,
    INVOICE,
    ORGANIZATION_ROW,
    PAYER_STATUS,
    PAYER_STATUS_FROM_BILLING,
    SETTLEMENT,
    SETTLEMENT_INVOICES,
    billing_response,
)
from ee.settings import BILLING_SERVICE_URL

PAYER_CLIENT_ID = "payer-partner"
PAYER_KEY_ID = "payer-key"
# Generated once for the module, because RSA key generation is slow and no test changes the key.
PAYER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class TestPayerProvisioningAPI(LicensedTestMixin, ProvisioningTestBase):
    def setUp(self):
        super().setUp()
        public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(PAYER_KEY.public_key()))
        public_jwk.update({"kid": PAYER_KEY_ID, "use": "sig", "alg": "RS256"})
        jwks = patch(
            "posthog.api.oauth.client_assertion.fetch_client_json_document", return_value=({"keys": [public_jwk]}, None)
        )
        jwks.start()
        self.addCleanup(jwks.stop)
        self.payer = OAuthApplication.objects.create(
            name="Paying Partner",
            client_id=PAYER_CLIENT_ID,
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            jwks_uri="https://payer.example.com/.well-known/jwks.json",
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://payer.example.com/callback",
            algorithm="RS256",
            scopes=TEST_PARTNER_SCOPES,
            organization=self.organization,
            is_provisioning_partner=True,
            _provisioning_config=provisioning_config(pays_for_customers=True),
        )

    def _client_assertion(self) -> dict[str, str]:
        now = int(time.time())
        claims = {
            "iss": PAYER_CLIENT_ID,
            "sub": PAYER_CLIENT_ID,
            "aud": settings.SITE_URL,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + 60,
        }
        return {
            "client_assertion": jwt.encode(claims, PAYER_KEY, algorithm="RS256", headers={"kid": PAYER_KEY_ID}),
            "client_assertion_type": CLIENT_ASSERTION_TYPE_JWT_BEARER,
        }

    def _call(self, method: str, path: str, data: dict[str, Any] | None = None):
        url = f"/api/agentic/provisioning/payer{path}"
        # A private_key_jwt partner sends its assertion in the query string on a GET and in the body otherwise.
        if method == "get":
            return self.client.get(url, {**(data or {}), **self._client_assertion()})
        return getattr(self.client, method)(
            url, data=json.dumps({**(data or {}), **self._client_assertion()}), content_type="application/json"
        )

    @parameterized.expand(
        [
            ("a public partner", "public"),
            ("a confidential partner that does not pay for its customers", "not_paying"),
            ("a paying partner without a verified organization", "unverified"),
        ]
    )
    def test_refuses_partners_that_cannot_reach_payer_routes(self, _name, partner_kind):
        with patch("ee.billing.billing_manager.http_session.request") as request:
            if partner_kind == "public":
                public_partner = OAuthApplication.objects.create(
                    name="Public Partner",
                    client_id="public-payer",
                    client_type=OAuthApplication.CLIENT_PUBLIC,
                    authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                    redirect_uris="https://public.example.com/callback",
                    algorithm="RS256",
                    organization=self.organization,
                    is_provisioning_partner=True,
                    _provisioning_config=provisioning_config(pays_for_customers=True),
                )
                response = self.client.get("/api/agentic/provisioning/payer", {"client_id": public_partner.client_id})
            elif partner_kind == "not_paying":
                response = self.client.get(
                    "/api/agentic/provisioning/payer", HTTP_AUTHORIZATION=self._basic_auth_header()
                )
            else:
                self.payer.organization = None
                self.payer.save()
                response = self._call("get", "")

        assert response.status_code == 403, response.json()
        assert response.json()["error"]["code"] == "forbidden"
        request.assert_not_called()

    @parameterized.expand(
        [
            ("status", "get", "", None, PAYER_STATUS_FROM_BILLING, ("GET", "/api/payer", None, None), PAYER_STATUS),
            (
                "update",
                "patch",
                "",
                {"webhook_url": "https://hooks.example.com/posthog", "spend_alert_usd": "1000"},
                PAYER_STATUS_FROM_BILLING,
                (
                    "PATCH",
                    "/api/payer",
                    None,
                    {"webhook_url": "https://hooks.example.com/posthog", "spend_alert_usd": "1000.00"},
                ),
                PAYER_STATUS,
            ),
            (
                "webhook secret",
                "post",
                "/webhook_secret",
                None,
                {"secret": "whsec_ZXhhbXBsZQ==", "created_at": "2026-10-05T12:00:00Z"},
                ("POST", "/api/payer/webhook_secret", None, None),
                {"secret": "whsec_ZXhhbXBsZQ==", "created_at": "2026-10-05T12:00:00Z"},
            ),
            (
                "test event",
                "post",
                "/test_event",
                None,
                {"event_id": "evt_example1"},
                ("POST", "/api/payer/test_event", None, None),
                {"event_id": "evt_example1"},
            ),
            (
                "organizations",
                "get",
                "/organizations",
                {"limit": "20", "offset": "40"},
                {"count": 41, "results": [ORGANIZATION_ROW]},
                ("GET", "/api/payer/organizations", {"limit": 20, "offset": 40}, None),
                {"count": 41, "results": [ORGANIZATION_ROW]},
            ),
            (
                "organization limits",
                "patch",
                f"/organizations/{CUSTOMER_ORGANIZATION_ID}/limits",
                {"custom_limits_usd": {"session_replay": 100}},
                ORGANIZATION_ROW,
                (
                    "PATCH",
                    f"/api/payer/organizations/{CUSTOMER_ORGANIZATION_ID}/limits",
                    None,
                    {"custom_limits_usd": {"session_replay": 100}},
                ),
                ORGANIZATION_ROW,
            ),
            (
                "invoices",
                "get",
                "/invoices",
                {"organization_id": CUSTOMER_ORGANIZATION_ID, "status": "paid"},
                {"count": 1, "results": [INVOICE]},
                ("GET", "/api/payer/invoices", {"organization_id": CUSTOMER_ORGANIZATION_ID, "status": "paid"}, None),
                {"count": 1, "results": [INVOICE]},
            ),
            (
                "settlements",
                "get",
                "/settlements",
                None,
                {"count": 1, "results": [SETTLEMENT]},
                ("GET", "/api/payer/settlements", {}, None),
                {"count": 1, "results": [SETTLEMENT]},
            ),
            (
                "settlement",
                "get",
                "/settlements/stl_example1",
                None,
                {**SETTLEMENT, "invoices": SETTLEMENT_INVOICES},
                ("GET", "/api/payer/settlements/stl_example1", None, None),
                {**SETTLEMENT, "invoices": SETTLEMENT_INVOICES},
            ),
        ]
    )
    def test_serves_each_route_from_billing(
        self, _name, method, path, body, billing_payload, expected_request, expected_response
    ):
        with patch(
            "ee.billing.billing_manager.http_session.request", return_value=billing_response(billing_payload)
        ) as request:
            response = self._call(method, path, body)

        assert response.status_code == 200, response.json()
        assert response.json() == expected_response
        expected_method, expected_path, expected_params, expected_body = expected_request
        assert request.call_args.args == (expected_method, f"{BILLING_SERVICE_URL}{expected_path}")
        assert request.call_args.kwargs["params"] == expected_params
        assert request.call_args.kwargs["json"] == expected_body

    def test_refuses_default_limits_which_only_organization_admins_change(self):
        with patch("ee.billing.billing_manager.http_session.request") as request:
            response = self._call("patch", "", {"default_limits_usd": {"product_analytics": 0}})

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"
        assert response.json()["error"]["message"].startswith("default_limits_usd: ")
        request.assert_not_called()

    @parameterized.expand(
        [
            (
                "billing rejects a field the partner sent",
                "patch",
                "",
                billing_response({"type": "validation_error", "attr": "webhook_url", "detail": BILLING_DETAIL}, 400),
                400,
                "invalid_request",
            ),
            (
                "another organization manages the payer",
                "patch",
                "",
                billing_response({"detail": BILLING_DETAIL}, 403),
                403,
                "forbidden",
            ),
            ("billing unreachable", "patch", "", requests.ConnectionError(BILLING_DETAIL), 502, "billing_unavailable"),
            (
                "billing answers without a key the contract requires",
                "post",
                "/webhook_secret",
                billing_response({"secret": "whsec_ZXhhbXBsZQ=="}),
                502,
                "billing_unavailable",
            ),
        ]
    )
    def test_answers_billing_refusals_in_the_provisioning_envelope(
        self, _name, method, path, outcome, expected_status, expected_code
    ):
        side_effect = outcome if isinstance(outcome, Exception) else [outcome]
        with patch("ee.billing.billing_manager.http_session.request", side_effect=side_effect):
            response = self._call(method, path, {"webhook_url": "https://hooks.example.com/posthog"})

        assert response.status_code == expected_status
        assert response.json()["type"] == "error"
        assert response.json()["error"]["code"] == expected_code
        assert BILLING_DETAIL not in response.content.decode()

    @parameterized.expand(
        [
            (
                "a rejected value",
                billing_response({"type": "validation_error", "attr": "webhook_url", "detail": BILLING_DETAIL}, 400),
                "invalid_request",
            ),
            ("a refused partner", billing_response({"detail": BILLING_DETAIL}, 403), "forbidden"),
        ]
    )
    def test_keeps_the_rate_limit_charge_when_billing_refuses(self, _name, refusal, expected_code):
        with (
            patched_budget(
                PayerView, "patch", "payer_writes", Budget(burst=1, per_hour=1), multipliers=FLAT_MULTIPLIERS
            ),
            patch("ee.billing.billing_manager.http_session.request", return_value=refusal) as request,
        ):
            refused = self._call("patch", "", {"webhook_url": "https://hooks.example.com/posthog"})
            retried = self._call("patch", "", {"webhook_url": "https://hooks.example.com/posthog"})

        assert refused.json()["error"]["code"] == expected_code
        assert retried.status_code == 429
        assert request.call_count == 1
