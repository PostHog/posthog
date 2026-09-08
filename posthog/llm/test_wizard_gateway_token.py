from datetime import timedelta
from decimal import Decimal

import pytest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

import requests

from posthog.llm.wizard_gateway_token import (
    _TIER_FLOORS,
    NO_OVERRIDE,
    WizardGatewayMintError,
    WizardLimitOverride,
    WizardTierLimits,
    mint_wizard_gateway_token,
    parse_limit_override,
    wizard_gateway_base_url,
    wizard_gateway_configured,
    wizard_limit_override,
    wizard_posture,
    wizard_product_node,
    wizard_program_cap,
    wizard_tier_limits,
)
from posthog.models.organization import Organization
from posthog.models.team.team import Team

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
        assert post.call_args.kwargs["json"]["ttl_seconds"] == 1800

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
        assert post.call_args.kwargs["json"]["cap_usd"] == "7.000000"

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

    def test_an_override_cap_replaces_the_setting(self):
        minted = {"token": "phe_x", "expires_at": "2026-08-22T00:00:00Z"}
        with patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(201, minted)) as post:
            mint_wizard_gateway_token(obo="org_1", user="user_1", cap_usd=Decimal("30"))
        assert post.call_args.kwargs["json"]["cap_usd"] == "30.000000"

    def test_secret_never_appears_in_the_error(self):
        with patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(403)):
            with pytest.raises(WizardGatewayMintError) as raised:
                mint_wizard_gateway_token(obo="org_1", user="user_1")
        assert "phs_wizard_secret" not in str(raised.value)


def _organization(*, age: timedelta = timedelta(days=30), features: list | None = None) -> Organization:
    # Unsaved: posture reads cached fields only, so no row is needed.
    return Organization(name="org", created_at=timezone.now() - age, available_product_features=features or [])


class TestWizardPosture:
    def test_a_young_organization_with_no_event_is_new(self):
        assert wizard_posture(_organization(age=timedelta(days=1)), Team(ingested_event=False)) == "new"

    def test_an_ingested_event_makes_it_active_whatever_its_age(self):
        assert wizard_posture(_organization(age=timedelta(days=1)), Team(ingested_event=True)) == "active"

    def test_an_old_organization_with_no_event_is_active(self):
        assert wizard_posture(_organization(age=timedelta(days=8)), Team(ingested_event=False)) == "active"

    def test_a_paid_plan_outranks_the_rest(self):
        # Any granted feature is a paid plan; a young, event-less paid org is paid.
        paid = _organization(age=timedelta(days=1), features=[{"key": "alerts", "name": "Alerts"}])
        assert wizard_posture(paid, Team(ingested_event=False)) == "paid"


class TestWizardTierLimits:
    @override_settings(WIZARD_GATEWAY_TIERS={"new": {"cap_usd": "5", "mints_per_day": 2, "ttl_seconds": "3600"}})
    def test_a_configured_tier_is_read_field_by_field(self):
        assert wizard_tier_limits("new") == WizardTierLimits(
            cap_usd=Decimal("5.000000"),
            max_cap_usd=_TIER_FLOORS["new"].max_cap_usd,
            mints_per_day=2,
            ttl_seconds=3600,
        )
        assert wizard_tier_limits("paid") == _TIER_FLOORS["paid"]

    @pytest.mark.parametrize(
        "tiers",
        [
            {"new": "lots"},
            # A non-dict entry that would satisfy `"cap_usd" in raw`.
            {"new": ["cap_usd", "mints_per_day", "ttl_seconds"]},
            {"new": {"cap_usd": "999", "mints_per_day": 0, "ttl_seconds": True}},
            {"new": {"cap_usd": "NaN", "mints_per_day": "two", "ttl_seconds": -1}},
            [],
            "not a dict",
        ],
    )
    def test_an_out_of_contract_tier_degrades_to_its_own_floor(self, tiers):
        with override_settings(WIZARD_GATEWAY_TIERS=tiers):
            assert wizard_tier_limits("new") == _TIER_FLOORS["new"]

    @override_settings(WIZARD_GATEWAY_TOKEN_CAP_USD_BY_PROGRAM={"self-driving": "6", "broken": "lots"})
    def test_a_program_cap_is_read_by_program_id(self):
        assert wizard_program_cap("self-driving") == Decimal("6.000000")
        assert wizard_program_cap("broken") is None
        assert wizard_program_cap("integration") is None
        assert wizard_program_cap(["self-driving"]) is None


class TestTieredMint:
    @pytest.fixture(autouse=True)
    def _mint_settings(self):
        with override_settings(
            **MINT_SETTINGS,
            WIZARD_GATEWAY_TIERS={
                "new": {"cap_usd": "5", "mints_per_day": 2, "ttl_seconds": 3600},
                "paid": {"cap_usd": "10", "mints_per_day": 10},
            },
            WIZARD_GATEWAY_TOKEN_CAP_USD_BY_PROGRAM={"ai-observability": "12"},
        ):
            yield

    def _mint(self, **kwargs):
        minted = {"token": "phe_x", "expires_at": "2026-08-22T00:00:00Z"}
        with patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(201, minted)) as post:
            mint_wizard_gateway_token(obo="org_1", user="user_1", **kwargs)
        return post.call_args.kwargs["json"]

    def test_the_tier_cap_and_ttl_apply(self):
        body = self._mint(program="integration", posture="new")
        assert (body["cap_usd"], body["ttl_seconds"]) == ("5.000000", 3600)

    def test_a_tier_without_a_ttl_keeps_its_floor_ttl(self):
        assert self._mint(program="integration", posture="paid")["ttl_seconds"] == _TIER_FLOORS["paid"].ttl_seconds

    def test_a_posture_without_a_tier_keeps_its_floor_cap(self):
        want = f"{_TIER_FLOORS['active'].cap_usd:f}"
        assert self._mint(program="integration", posture="active")["cap_usd"] == want

    def test_the_program_cap_is_bounded_by_the_postures_ceiling(self):
        assert self._mint(program="ai-observability", posture="new")["cap_usd"] == "6.000000"
        assert self._mint(program="ai-observability", posture="paid")["cap_usd"] == "12.000000"

    def test_no_posture_ignores_the_caller_supplied_program_cap(self):
        # The one path with no ceiling to bound it, so the program a caller
        # names must not choose the cap there.
        assert self._mint(program="ai-observability")["cap_usd"] == "25.000000"

    def test_the_override_outranks_both(self):
        assert self._mint(program="ai-observability", posture="new", cap_usd=Decimal("30"))["cap_usd"] == "30.000000"

    def test_no_posture_and_no_program_is_the_flat_cap(self):
        assert self._mint()["cap_usd"] == "25.000000"


class TestParseLimitOverride:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (
                {"cap_usd": "30", "mints_per_day": 100},
                WizardLimitOverride(cap_usd=Decimal("30.000000"), mints_per_day=100),
            ),
            (
                '{"cap_usd": 12.5, "mints_per_day": "50"}',
                WizardLimitOverride(cap_usd=Decimal("12.500000"), mints_per_day=50),
            ),
            ({"mints_per_day": 100}, WizardLimitOverride(cap_usd=None, mints_per_day=100)),
            ({"cap_usd": "lots", "mints_per_day": 100}, WizardLimitOverride(cap_usd=None, mints_per_day=100)),
            (
                {"cap_usd": "30", "mints_per_day": 0},
                WizardLimitOverride(cap_usd=Decimal("30.000000"), mints_per_day=None),
            ),
            (None, NO_OVERRIDE),
            ("not json", NO_OVERRIDE),
            ([], NO_OVERRIDE),
            ({}, NO_OVERRIDE),
        ],
    )
    def test_payload_is_validated_field_by_field(self, raw, expected):
        assert parse_limit_override(raw) == expected

    @pytest.mark.parametrize("cap", ["0", "-5", "31", "20000", "NaN", "Infinity", "1e100000", "0.0000001", True, None])
    def test_a_cap_outside_the_gateway_contract_is_ignored(self, cap):
        assert parse_limit_override({"cap_usd": cap}) == NO_OVERRIDE

    @pytest.mark.parametrize("mints", [0, -1, 151, 2.5, "2.5", "abc", True, None])
    def test_mints_outside_the_bounds_are_ignored(self, mints):
        assert parse_limit_override({"mints_per_day": mints}) == NO_OVERRIDE


class TestWizardLimitOverride:
    def test_evaluates_the_flag_for_the_user_org_and_project(self):
        with patch(
            "posthog.llm.wizard_gateway_token.posthoganalytics.get_feature_flag_payload",
            return_value={"cap_usd": "30"},
        ) as get_payload:
            override = wizard_limit_override(
                distinct_id="d1", email="eng@posthog.com", organization_id="org_1", team_id=7
            )

        assert override == WizardLimitOverride(cap_usd=Decimal("30.000000"), mints_per_day=None)
        get_payload.assert_called_once_with(
            "wizard-gateway-limit-override",
            "d1",
            person_properties={"email": "eng@posthog.com", "organization_id": "org_1", "team_id": "7"},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

    def test_a_flag_outage_fails_closed(self):
        with patch(
            "posthog.llm.wizard_gateway_token.posthoganalytics.get_feature_flag_payload",
            side_effect=RuntimeError("down"),
        ):
            assert (
                wizard_limit_override(distinct_id="d1", email=None, organization_id="org_1", team_id=7) == NO_OVERRIDE
            )


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
