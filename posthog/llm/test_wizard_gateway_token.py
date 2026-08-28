import pytest
from unittest.mock import patch

from django.test import override_settings

import requests

from posthog.llm.wizard_gateway_token import (
    WizardGatewayMintError,
    mint_wizard_gateway_token,
    wizard_gateway_base_url,
    wizard_gateway_configured,
    wizard_product_node,
)

MINT_SETTINGS = {
    "WIZARD_GATEWAY_URL": "https://ai-gateway.us.posthog.com",
    "WIZARD_GATEWAY_MINT_KEY": "phs_wizard_secret",
    "WIZARD_GATEWAY_CLIENT_IDS": ["wizard-client-id"],
    # Not _DEFAULT_CAP_USD: equal values make the honored-setting and fell-back
    # assertions indistinguishable.
    "WIZARD_GATEWAY_TOKEN_CAP_USD": "25",
    "WIZARD_GATEWAY_TOKEN_TTL_SECONDS": 86400,
    "WIZARD_GATEWAY_PROGRAM_IDS": ["integration"],
}


class _Response:
    def __init__(self, status_code: int, payload=None, raise_on_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise_on_json = raise_on_json
        self.text = "body"

    def json(self):
        if self._raise_on_json:
            raise ValueError("not json")
        return self._payload


class TestMintWizardGatewayToken:
    @pytest.fixture(autouse=True)
    def _mint_settings(self):
        with override_settings(**MINT_SETTINGS):
            yield

    def test_posts_pinned_attribution_and_bearer(self):
        minted = {"token": "phe_x", "expires_at": "2026-08-22T00:00:00Z", "cap_usd": "25"}
        with patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(201, minted)) as post:
            assert mint_wizard_gateway_token(obo="org_1", user="user_1") == minted

        assert post.call_args[0][0] == "https://ai-gateway.us.posthog.com/v1/tokens"
        assert post.call_args.kwargs["json"] == {
            "cap_usd": "25.000000",
            "ttl_seconds": 86400,
            "product": "wizard",
            "obo": "org_1",
            "user": "user_1",
        }
        assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer phs_wizard_secret"}
        assert post.call_args.kwargs["timeout"] > 0

    @override_settings(WIZARD_GATEWAY_URL="https://ai-gateway.us.posthog.com/v1/")
    def test_version_suffixed_setting_does_not_double_up(self):
        # The setting may carry /v1; both the mint path and the base handed to the
        # CLI must come out the same regardless.
        assert wizard_gateway_base_url() == "https://ai-gateway.us.posthog.com"
        minted = {"token": "phe_x", "expires_at": "2026-08-22T00:00:00Z"}
        with patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(201, minted)) as post:
            mint_wizard_gateway_token(obo="org_1", user="user_1")
        assert post.call_args[0][0] == "https://ai-gateway.us.posthog.com/v1/tokens"

    @override_settings(WIZARD_GATEWAY_TOKEN_TTL_SECONDS=172800)
    def test_ttl_clamped_to_gateway_ceiling(self):
        minted = {"token": "phe_x", "expires_at": "2026-08-22T00:00:00Z"}
        with patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(201, minted)) as post:
            mint_wizard_gateway_token(obo="org_1", user="user_1")
        assert post.call_args.kwargs["json"]["ttl_seconds"] == 86400

    @override_settings(WIZARD_GATEWAY_TOKEN_TTL_SECONDS=5)
    def test_ttl_clamped_to_a_ttl_that_outlives_a_run(self):
        minted = {"token": "phe_x", "expires_at": "2026-08-22T00:00:00Z"}
        with patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(201, minted)) as post:
            mint_wizard_gateway_token(obo="org_1", user="user_1")
        assert post.call_args.kwargs["json"]["ttl_seconds"] == 3600

    @pytest.mark.parametrize(
        "response",
        [
            _Response(429),
            _Response(500),
            _Response(200, {"token": "phe_x", "expires_at": "z"}),  # only 201 is a mint
        ],
    )
    def test_non_201_raises(self, response):
        with patch("posthog.llm.wizard_gateway_token.requests.post", return_value=response):
            with pytest.raises(WizardGatewayMintError):
                mint_wizard_gateway_token(obo="org_1", user="user_1")

    def test_transport_failure_raises(self):
        with patch(
            "posthog.llm.wizard_gateway_token.requests.post",
            side_effect=requests.RequestException("connection reset"),
        ):
            with pytest.raises(WizardGatewayMintError):
                mint_wizard_gateway_token(obo="org_1", user="user_1")

    def test_non_json_body_raises(self):
        with patch(
            "posthog.llm.wizard_gateway_token.requests.post",
            return_value=_Response(201, raise_on_json=True),
        ):
            with pytest.raises(WizardGatewayMintError):
                mint_wizard_gateway_token(obo="org_1", user="user_1")

    @pytest.mark.parametrize(
        "payload",
        [
            {"expires_at": "2026-08-22T00:00:00Z"},  # no token
            {"token": "phe_x"},  # no expiry, so the CLI cannot refresh
            [],  # not an object
        ],
    )
    def test_incomplete_payload_raises(self, payload):
        with patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(201, payload)):
            with pytest.raises(WizardGatewayMintError):
                mint_wizard_gateway_token(obo="org_1", user="user_1")

    @pytest.mark.parametrize(
        "configured",
        [
            "not a number",
            "0",
            "-5",
            "20000",
            # Reaches the quantize guard: the result needs more digits than the
            # decimal context allows, so quantize raises rather than returning.
            "1e100000",
            # Parse as Decimals but are not finite, so the is_finite branch is the
            # only thing between them and the gateway.
            "NaN",
            "Infinity",
            "",
            # Positive but under a microdollar: it quantizes to 0.000000, which
            # the gateway rejects as non-positive.
            "0.0000001",
        ],
    )
    def test_out_of_contract_cap_falls_back_to_the_default(self, configured):
        minted = {"token": "phe_x", "expires_at": "2026-08-22T00:00:00Z"}
        with override_settings(WIZARD_GATEWAY_TOKEN_CAP_USD=configured):
            with patch(
                "posthog.llm.wizard_gateway_token.requests.post",
                return_value=_Response(201, minted),
            ) as post:
                mint_wizard_gateway_token(obo="org_1", user="user_1")
        assert post.call_args.kwargs["json"]["cap_usd"] == "20.000000"

    @pytest.mark.parametrize(
        "raised,token_may_exist",
        [
            # Never reached the gateway, so nothing was issued.
            (requests.exceptions.ConnectionError("refused"), False),
            (requests.exceptions.ConnectTimeout("connect timed out"), False),
            # The request may have landed; the gateway could hold a token.
            (requests.exceptions.ReadTimeout("read timed out"), True),
        ],
    )
    def test_transport_failures_report_whether_a_token_may_exist(self, raised, token_may_exist):
        with patch("posthog.llm.wizard_gateway_token.requests.post", side_effect=raised):
            with pytest.raises(WizardGatewayMintError) as excinfo:
                mint_wizard_gateway_token(obo="org_1", user="user_1")
        assert excinfo.value.token_may_exist is token_may_exist

    def test_a_refusal_reports_that_no_token_exists(self):
        with patch(
            "posthog.llm.wizard_gateway_token.requests.post",
            return_value=_Response(400, {"error": "bad request"}),
        ):
            with pytest.raises(WizardGatewayMintError) as excinfo:
                mint_wizard_gateway_token(obo="org_1", user="user_1")
        assert excinfo.value.token_may_exist is False

    def test_an_unreadable_201_reports_that_a_token_may_exist(self):
        # The gateway said it minted; we just could not read it back. Refunding the
        # slot here would let the ceiling be exceeded by a token that is live.
        with patch(
            "posthog.llm.wizard_gateway_token.requests.post",
            return_value=_Response(201, {"not": "a token"}),
        ):
            with pytest.raises(WizardGatewayMintError) as excinfo:
                mint_wizard_gateway_token(obo="org_1", user="user_1")
        assert excinfo.value.token_may_exist is True

    @override_settings(WIZARD_GATEWAY_TOKEN_CAP_USD="12.5")
    def test_in_contract_cap_is_sent_as_fixed_point(self):
        minted = {"token": "phe_x", "expires_at": "2026-08-22T00:00:00Z"}
        with patch(
            "posthog.llm.wizard_gateway_token.requests.post",
            return_value=_Response(201, minted),
        ) as post:
            mint_wizard_gateway_token(obo="org_1", user="user_1")
        assert post.call_args.kwargs["json"]["cap_usd"] == "12.500000"

    def test_secret_never_appears_in_the_error(self):
        with patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(403)):
            with pytest.raises(WizardGatewayMintError) as raised:
                mint_wizard_gateway_token(obo="org_1", user="user_1")
        assert "phs_wizard_secret" not in str(raised.value)


class TestWizardGatewayConfigured:
    def test_all_four_present(self):
        with override_settings(**MINT_SETTINGS):
            assert wizard_gateway_configured() is True

    @pytest.mark.parametrize(
        "missing",
        [
            "WIZARD_GATEWAY_URL",
            "WIZARD_GATEWAY_MINT_KEY",
            "WIZARD_GATEWAY_CLIENT_IDS",
            # An empty program list refuses every program, so leaving it out is an
            # unconfigured deploy, not a fleet of callers sending bad names.
            "WIZARD_GATEWAY_PROGRAM_IDS",
        ],
    )
    def test_any_missing_piece_disables(self, missing):
        blank: dict = {
            **MINT_SETTINGS,
            missing: [] if missing in ("WIZARD_GATEWAY_CLIENT_IDS", "WIZARD_GATEWAY_PROGRAM_IDS") else "",
        }
        with override_settings(**blank):
            assert wizard_gateway_configured() is False


class TestWizardProductNode:
    @override_settings(WIZARD_GATEWAY_PROGRAM_IDS=["integration", "audit"])
    def test_a_configured_program_gets_its_own_node(self):
        assert wizard_product_node("audit") == "wizard:audit"

    @override_settings(WIZARD_GATEWAY_PROGRAM_IDS=["integration"])
    def test_an_unknown_program_is_refused(self):
        assert wizard_product_node("../../etc") is None
        assert wizard_product_node("not-a-program") is None
        assert wizard_product_node("") is None
        assert wizard_product_node(None) is None

    @override_settings(WIZARD_GATEWAY_PROGRAM_IDS=[])
    def test_no_configured_programs_refuses_every_program(self):
        assert wizard_product_node("audit") is None
