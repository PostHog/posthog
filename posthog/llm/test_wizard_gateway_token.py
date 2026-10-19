import json
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

import pytest
from unittest.mock import call, patch

from django.test import override_settings
from django.utils import timezone

import requests

from posthog.llm.wizard_gateway_token import (
    _TIER_FLOORS,
    NO_OVERRIDE,
    WIZARD_DEFAULT_EFFORTS,
    WIZARD_DEFAULT_MODELS,
    WIZARD_DEFAULT_PROGRAMS,
    WIZARD_EFFORT_LEVELS,
    WIZARD_GATEWAY_ALLOWLIST_FLAG,
    WIZARD_GATEWAY_CONFIG_REJECTS,
    WIZARD_SYSTEM_PROMPT_FLAG,
    WizardGatewayMintError,
    WizardGatewayPolicy,
    WizardLimitOverride,
    WizardSystemPrompt,
    WizardTierLimits,
    mint_wizard_gateway_token,
    normalize_model,
    parse_limit_override,
    wizard_gateway_base_url,
    wizard_gateway_configured,
    wizard_gateway_policy,
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
    "WIZARD_GATEWAY_MINT_URL": "",
    "WIZARD_GATEWAY_MINT_KEY": "phs_wizard_secret",
    "WIZARD_GATEWAY_CLIENT_IDS": ["wizard-client-id"],
    # Not _DEFAULT_CAP_USD: equal values make the honored-setting and fell-back
    # assertions indistinguishable.
    "WIZARD_GATEWAY_TOKEN_CAP_USD": "25",
    "WIZARD_GATEWAY_TOKEN_TTL_SECONDS": 86400,
}

# Trailing whitespace and an accent: the mint must carry the text byte for byte.
PROMPT_TEXT = "You are the wizard. [posthog:abort]\n é"

POLICY = WizardGatewayPolicy(
    # Mixed case, a provider prefix, a duplicate and stray spaces: the mint sends the gateway's spelling.
    models=("OpenAI/GPT-5.6-Luna", "gpt-5.6-luna", " Claude-Sonnet-5 "),
    efforts=("none", "high"),
    programs=("integration", "audit"),
    prompt=WizardSystemPrompt(text=PROMPT_TEXT),
)

PROMPT_PAYLOAD = {"version": 4, "text": PROMPT_TEXT}
ALLOWLIST_PAYLOAD = {
    "models": ["OpenAI/GPT-5.6-Luna", "claude-sonnet-5"],
    "efforts": ["high", "none"],
    "programs": ["integration", "audit"],
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

    @pytest.mark.parametrize(
        "mint_url,expected_url",
        [
            ("", "https://ai-gateway.us.posthog.com/v1/tokens"),
            ("http://localhost:8080", "http://localhost:8080/v1/tokens"),
            ("http://localhost:8080/v1/", "http://localhost:8080/v1/tokens"),
        ],
    )
    def test_posts_pinned_attribution_and_bearer(self, mint_url: str, expected_url: str) -> None:
        minted = {"token": "phe_x", "expires_at": "2026-08-22T00:00:00Z", "cap_usd": "25"}
        with (
            override_settings(WIZARD_GATEWAY_MINT_URL=mint_url),
            patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(201, minted)) as post,
        ):
            assert mint_wizard_gateway_token(obo="7", user="user_1", policy=POLICY) == minted
            assert wizard_gateway_base_url() == "https://ai-gateway.us.posthog.com"

        assert post.call_args[0][0] == expected_url
        assert post.call_args.kwargs["json"] == {
            "cap_usd": "25.000000",
            "ttl_seconds": 86400,
            "product": "wizard",
            "obo": "7",
            "user": "user_1",
            "allowed_models": ["gpt-5.6-luna", "claude-sonnet-5"],
            "allowed_efforts": ["none", "high"],
            "system_prompt": PROMPT_TEXT,
        }
        assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer phs_wizard_secret"}
        assert post.call_args.kwargs["timeout"] > 0


class TestWizardMintRequest:
    @override_settings(WIZARD_GATEWAY_URL="https://ai-gateway.us.posthog.com/v1/", WIZARD_GATEWAY_MINT_URL="")
    def test_version_suffixed_setting_does_not_double_up(self):
        # The setting may carry /v1; both the mint path and the base handed to the
        # CLI must come out the same regardless.
        assert wizard_gateway_base_url() == "https://ai-gateway.us.posthog.com"
        minted = {"token": "phe_x", "expires_at": "2026-08-22T00:00:00Z"}
        with patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(201, minted)) as post:
            mint_wizard_gateway_token(obo="7", user="user_1", policy=POLICY)
        assert post.call_args[0][0] == "https://ai-gateway.us.posthog.com/v1/tokens"

    @override_settings(WIZARD_GATEWAY_TOKEN_TTL_SECONDS=172800)
    def test_ttl_clamped_to_gateway_ceiling(self):
        minted = {"token": "phe_x", "expires_at": "2026-08-22T00:00:00Z"}
        with patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(201, minted)) as post:
            mint_wizard_gateway_token(obo="7", user="user_1", policy=POLICY)
        assert post.call_args.kwargs["json"]["ttl_seconds"] == 86400

    @override_settings(WIZARD_GATEWAY_TOKEN_TTL_SECONDS=5)
    def test_ttl_clamped_to_a_ttl_that_outlives_a_run(self):
        minted = {"token": "phe_x", "expires_at": "2026-08-22T00:00:00Z"}
        with patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(201, minted)) as post:
            mint_wizard_gateway_token(obo="7", user="user_1", policy=POLICY)
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
                mint_wizard_gateway_token(obo="7", user="user_1", policy=POLICY)

    def test_transport_failure_raises(self):
        with patch(
            "posthog.llm.wizard_gateway_token.requests.post",
            side_effect=requests.RequestException("connection reset"),
        ):
            with pytest.raises(WizardGatewayMintError):
                mint_wizard_gateway_token(obo="7", user="user_1", policy=POLICY)

    def test_non_json_body_raises(self):
        with patch(
            "posthog.llm.wizard_gateway_token.requests.post",
            return_value=_Response(201, raise_on_json=True),
        ):
            with pytest.raises(WizardGatewayMintError):
                mint_wizard_gateway_token(obo="7", user="user_1", policy=POLICY)

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
                mint_wizard_gateway_token(obo="7", user="user_1", policy=POLICY)

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
                mint_wizard_gateway_token(obo="7", user="user_1", policy=POLICY)
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
                mint_wizard_gateway_token(obo="7", user="user_1", policy=POLICY)
        assert excinfo.value.token_may_exist is token_may_exist

    def test_a_refusal_reports_that_no_token_exists(self):
        with patch(
            "posthog.llm.wizard_gateway_token.requests.post",
            return_value=_Response(400, {"error": "bad request"}),
        ):
            with pytest.raises(WizardGatewayMintError) as excinfo:
                mint_wizard_gateway_token(obo="7", user="user_1", policy=POLICY)
        assert excinfo.value.token_may_exist is False

    def test_an_unreadable_201_reports_that_a_token_may_exist(self):
        # The gateway said it minted; we just could not read it back. Refunding the
        # slot here would let the ceiling be exceeded by a token that is live.
        with patch(
            "posthog.llm.wizard_gateway_token.requests.post",
            return_value=_Response(201, {"not": "a token"}),
        ):
            with pytest.raises(WizardGatewayMintError) as excinfo:
                mint_wizard_gateway_token(obo="7", user="user_1", policy=POLICY)
        assert excinfo.value.token_may_exist is True

    @override_settings(WIZARD_GATEWAY_TOKEN_CAP_USD="12.5")
    def test_in_contract_cap_is_sent_as_fixed_point(self):
        minted = {"token": "phe_x", "expires_at": "2026-08-22T00:00:00Z"}
        with patch(
            "posthog.llm.wizard_gateway_token.requests.post",
            return_value=_Response(201, minted),
        ) as post:
            mint_wizard_gateway_token(obo="7", user="user_1", policy=POLICY)
        assert post.call_args.kwargs["json"]["cap_usd"] == "12.500000"

    def test_an_override_cap_replaces_the_setting(self):
        minted = {"token": "phe_x", "expires_at": "2026-08-22T00:00:00Z"}
        with patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(201, minted)) as post:
            mint_wizard_gateway_token(obo="7", user="user_1", policy=POLICY, cap_usd=Decimal("30"))
        assert post.call_args.kwargs["json"]["cap_usd"] == "30.000000"

    def test_secret_never_appears_in_the_error(self):
        with patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(403)):
            with pytest.raises(WizardGatewayMintError) as raised:
                mint_wizard_gateway_token(obo="7", user="user_1", policy=POLICY)
        assert "phs_wizard_secret" not in str(raised.value)


def _organization(
    *, age: timedelta = timedelta(days=30), features: list | None = None, subscribed: bool | None = None
) -> Organization:
    # Unsaved: posture reads cached fields only, so no row is needed.
    return Organization(
        name="org",
        created_at=timezone.now() - age,
        available_product_features=features or [],
        has_active_subscription=subscribed,
    )


class TestWizardPosture:
    def test_a_young_organization_with_no_event_is_new(self):
        assert wizard_posture(_organization(age=timedelta(days=1)), Team(ingested_event=False)) == "new"

    def test_an_ingested_event_makes_it_active_whatever_its_age(self):
        assert wizard_posture(_organization(age=timedelta(days=1)), Team(ingested_event=True)) == "active"

    def test_an_old_organization_with_no_event_is_active(self):
        assert wizard_posture(_organization(age=timedelta(days=8)), Team(ingested_event=False)) == "active"

    def test_a_subscription_outranks_the_rest(self):
        paid = _organization(age=timedelta(days=1), subscribed=True)
        assert wizard_posture(paid, Team(ingested_event=False)) == "paid"

    def test_a_cancelled_organization_keeps_its_features_but_loses_the_paid_tier(self):
        # Billing leaves the feature list populated after a cancellation, so the
        # feature-derived tier would go on handing it the widest limits.
        cancelled = _organization(features=[{"key": "alerts", "name": "Alerts"}], subscribed=False)
        assert wizard_posture(cancelled, Team(ingested_event=True)) == "active"

    def test_an_unsynced_organization_falls_back_to_its_plan_tier(self):
        licensed = _organization(features=[{"key": "alerts", "name": "Alerts"}], subscribed=None)
        assert wizard_posture(licensed, Team(ingested_event=False)) == "paid"
        assert wizard_posture(_organization(subscribed=None), Team(ingested_event=True)) == "active"


class TestWizardTierLimits:
    @override_settings(WIZARD_GATEWAY_TIERS={"new": {"cap_usd": "5", "mints_per_week": 2, "ttl_seconds": "3600"}})
    def test_a_configured_tier_is_read_field_by_field(self):
        assert wizard_tier_limits("new") == WizardTierLimits(
            cap_usd=Decimal("5.000000"),
            max_cap_usd=_TIER_FLOORS["new"].max_cap_usd,
            mints_per_week=2,
            ttl_seconds=3600,
        )
        assert wizard_tier_limits("paid") == _TIER_FLOORS["paid"]

    @override_settings(WIZARD_GATEWAY_TIERS={"new": {"cap_usd": "5", "max_cap_usd": "3"}})
    def test_a_ceiling_under_its_own_cap_is_ignored(self):
        # Honouring it would let a program entry tighten the cap rather than size it.
        limits = wizard_tier_limits("new")
        assert limits.cap_usd == Decimal("5.000000")
        assert limits.max_cap_usd == _TIER_FLOORS["new"].max_cap_usd

    @pytest.mark.parametrize(
        "tiers",
        [
            {"new": "lots"},
            # A non-dict entry that would satisfy `"cap_usd" in raw`.
            {"new": ["cap_usd", "mints_per_week", "ttl_seconds"]},
            {"new": {"cap_usd": "999", "mints_per_week": 0, "ttl_seconds": True}},
            {"new": {"cap_usd": "NaN", "mints_per_week": "two", "ttl_seconds": -1}},
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
                "new": {"cap_usd": "5", "mints_per_week": 2, "ttl_seconds": 3600},
                "paid": {"cap_usd": "10", "mints_per_week": 10},
            },
            WIZARD_GATEWAY_TOKEN_CAP_USD_BY_PROGRAM={"ai-observability": "12"},
        ):
            yield

    def _mint(self, **kwargs):
        minted = {"token": "phe_x", "expires_at": "2026-08-22T00:00:00Z"}
        with patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(201, minted)) as post:
            mint_wizard_gateway_token(obo="7", user="user_1", policy=POLICY, **kwargs)
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
                {"cap_usd": "30", "mints_per_week": 100},
                WizardLimitOverride(cap_usd=Decimal("30.000000"), mints_per_week=100),
            ),
            (
                '{"cap_usd": 12.5, "mints_per_week": "50"}',
                WizardLimitOverride(cap_usd=Decimal("12.500000"), mints_per_week=50),
            ),
            ({"mints_per_week": 100}, WizardLimitOverride(cap_usd=None, mints_per_week=100)),
            ({"cap_usd": "lots", "mints_per_week": 100}, WizardLimitOverride(cap_usd=None, mints_per_week=100)),
            (
                {"cap_usd": "30", "mints_per_week": 0},
                WizardLimitOverride(cap_usd=Decimal("30.000000"), mints_per_week=None),
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
        assert parse_limit_override({"mints_per_week": mints}) == NO_OVERRIDE


class TestWizardLimitOverride:
    def test_evaluates_the_flag_for_the_user_org_and_project(self):
        with patch(
            "posthog.llm.wizard_gateway_token.posthoganalytics.get_feature_flag_payload",
            return_value={"cap_usd": "30"},
        ) as get_payload:
            override = wizard_limit_override(
                distinct_id="d1", email="eng@posthog.com", organization_id="org_1", team_id=7
            )

        assert override == WizardLimitOverride(cap_usd=Decimal("30.000000"), mints_per_week=None)
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
    def test_all_three_present(self):
        with override_settings(**MINT_SETTINGS):
            assert wizard_gateway_configured() is True

    @pytest.mark.parametrize(
        "missing",
        [
            "WIZARD_GATEWAY_URL",
            "WIZARD_GATEWAY_MINT_KEY",
            "WIZARD_GATEWAY_CLIENT_IDS",
        ],
    )
    def test_any_missing_piece_disables(self, missing):
        blank: dict = {
            **MINT_SETTINGS,
            missing: [] if missing == "WIZARD_GATEWAY_CLIENT_IDS" else "",
        }
        with override_settings(**blank):
            assert wizard_gateway_configured() is False


class TestWizardProductNode:
    def test_a_program_on_the_allowlist_gets_its_own_node(self):
        assert wizard_product_node("audit", POLICY) == "wizard:audit"

    def test_a_program_off_the_allowlist_is_refused(self):
        assert wizard_product_node("../../etc", POLICY) is None
        assert wizard_product_node("not-a-program", POLICY) is None
        assert wizard_product_node("", POLICY) is None
        assert wizard_product_node(None, POLICY) is None
        assert wizard_product_node(["integration"], POLICY) is None


def _policy() -> WizardGatewayPolicy:
    return wizard_gateway_policy(distinct_id="d1", email="eng@posthog.com", organization_id="org_1", team_id=7)


class TestWizardGatewayPolicy:
    @staticmethod
    @contextmanager
    def _flags(prompt=PROMPT_PAYLOAD, allowlist=ALLOWLIST_PAYLOAD):
        def reader(payloads):
            def read(key, *args, **kwargs):
                value = payloads.get(key)
                if isinstance(value, Exception):
                    raise value
                return value

            return read

        with patch(
            "posthog.llm.wizard_gateway_token.posthoganalytics.get_feature_flag_payload",
            side_effect=reader({WIZARD_SYSTEM_PROMPT_FLAG: prompt, WIZARD_GATEWAY_ALLOWLIST_FLAG: allowlist}),
        ) as evaluated:
            yield evaluated

    def test_both_flags_make_the_policy(self):
        with self._flags():
            policy = _policy()

        assert policy == WizardGatewayPolicy(
            models=("OpenAI/GPT-5.6-Luna", "claude-sonnet-5"),
            efforts=("none", "high"),
            programs=("integration", "audit"),
            prompt=WizardSystemPrompt(text=PROMPT_TEXT),
        )

    def test_the_prompt_text_is_kept_untrimmed(self):
        text = "  [posthog:abort] \n"
        with self._flags(prompt={"version": 1, "text": text}):
            policy = _policy()
        assert policy.prompt is not None
        assert policy.prompt.text == text

    def test_both_flags_are_read_with_the_override_flags_targeting_properties(self):
        with self._flags() as evaluated:
            _policy()

        properties = {"email": "eng@posthog.com", "organization_id": "org_1", "team_id": "7"}
        assert evaluated.call_args_list == [
            # The prompt read sends its flag event and adds no network time to the mint.
            call(
                WIZARD_SYSTEM_PROMPT_FLAG,
                "d1",
                person_properties=properties,
                only_evaluate_locally=True,
                send_feature_flag_events=True,
            ),
            call(
                WIZARD_GATEWAY_ALLOWLIST_FLAG,
                "d1",
                person_properties=properties,
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            ),
        ]

    @pytest.mark.parametrize("missing", [None, RuntimeError("flags down")])
    @pytest.mark.parametrize(
        "flag,message",
        [
            (WIZARD_SYSTEM_PROMPT_FLAG, "system prompt flag"),
            (WIZARD_GATEWAY_ALLOWLIST_FLAG, "allowlist flag"),
        ],
    )
    def test_a_flag_that_returns_nothing_is_logged(self, flag, message, missing):
        # The SDK swallows its own errors and returns None, so None is the outage a
        # production mint sees; the exception is the same outage in a client that raises.
        kwargs = {"prompt": missing} if flag == WIZARD_SYSTEM_PROMPT_FLAG else {"allowlist": missing}
        with self._flags(**kwargs), patch("posthog.llm.wizard_gateway_token.logger") as log:
            _policy()

        logged = [call.args[0] for call in log.warning.call_args_list]
        expected = f"wizard_gateway_token: {message} " + ("returned no payload" if missing is None else "unavailable")
        assert logged == [expected]

    def test_models_that_spell_one_model_do_not_count_twice_against_the_gateways_cap(self):
        names = [f"m{i}" for i in range(31)]
        allowlist = {
            "models": [*names, "gpt-x", "openai/gpt-x", "GPT-X"],
            "efforts": ["high"],
            "programs": ["integration"],
        }
        with self._flags(allowlist=allowlist):
            policy = _policy()

        assert policy.programs == ("integration",)

    def test_a_program_id_saved_with_stray_spaces_is_stored_stripped(self):
        allowlist = {**ALLOWLIST_PAYLOAD, "programs": ["posthog-integration ", " audit"]}
        with self._flags(allowlist=allowlist):
            policy = _policy()

        assert policy.programs == ("posthog-integration", "audit")
        assert wizard_product_node("posthog-integration", policy) == "wizard:posthog-integration"

    def test_the_defaults_stay_inside_what_the_gateway_and_the_cli_accept(self):
        # The fallback pins every run when the allowlist flag is unreadable, so a
        # level the gateway does not know, or a model it spells differently,
        # would refuse them all.
        assert set(WIZARD_DEFAULT_EFFORTS) <= set(WIZARD_EFFORT_LEVELS)
        assert "max" not in WIZARD_DEFAULT_EFFORTS
        for model in WIZARD_DEFAULT_MODELS:
            assert normalize_model(model) == model, model

    @pytest.mark.parametrize(
        "payload",
        [
            {"text": PROMPT_TEXT},
            {"version": 4, "text": PROMPT_TEXT},
            {"version": "not a number", "text": PROMPT_TEXT},
            {"version": None, "text": PROMPT_TEXT},
        ],
    )
    def test_a_version_in_the_payload_is_tolerated_and_ignored(self, payload):
        with self._flags(prompt=payload):
            policy = _policy()
        assert policy.prompt == WizardSystemPrompt(text=PROMPT_TEXT)

    def test_the_prompt_text_stays_out_of_a_repr(self):
        assert PROMPT_TEXT not in repr(POLICY)
        assert PROMPT_TEXT not in repr(POLICY.prompt)

    def test_a_json_string_payload_reads_like_an_object(self):
        with self._flags(prompt=json.dumps(PROMPT_PAYLOAD), allowlist=json.dumps(ALLOWLIST_PAYLOAD)):
            policy = _policy()
        assert policy.prompt is not None
        assert policy.prompt.text == PROMPT_TEXT
        assert policy.programs == ("integration", "audit")

    @staticmethod
    def _rejects(field: str) -> float:
        return WIZARD_GATEWAY_CONFIG_REJECTS.labels(field=field)._value.get()

    @pytest.mark.parametrize(
        "prompt,counted",
        [
            # Off or unreadable is quiet: a flag outage is not a bad payload.
            (None, False),
            (RuntimeError("flags down"), False),
            ("not json", True),
            ([], True),
            ({"version": 4}, True),
            ({"version": 4, "text": ""}, True),
            ({"version": 4, "text": 7}, True),
            ({"version": 4, "text": "no marker here"}, True),
            # 16385 bytes: the cap counts bytes, not characters.
            ({"version": 4, "text": "[posthog:abort]" + "é" * 8185}, True),
            # The gateway refuses these two, so they must never reach it.
            ({"version": 4, "text": "[posthog:abort] \ud800"}, True),
            ({"version": 4, "text": "[posthog:abort] \ufffd"}, True),
        ],
    )
    def test_an_unusable_prompt_flag_leaves_the_token_unpinned(self, prompt, counted):
        before = self._rejects("system_prompt")
        with self._flags(prompt=prompt):
            policy = _policy()

        assert policy.prompt is None
        # The allowlist is read on its own and is untouched.
        assert policy.programs == ("integration", "audit")
        assert self._rejects("system_prompt") == before + (1 if counted else 0)

    def test_a_prompt_of_exactly_the_gateways_byte_cap_is_carried(self):
        text = "[posthog:abort]" + "é" * 8184  # 15 + 16368 = 16383 bytes
        text += "a"
        assert len(text.encode("utf-8")) == 16384
        with self._flags(prompt={"text": text}):
            policy = _policy()
        assert policy.prompt is not None
        assert policy.prompt.text == text

    @pytest.mark.parametrize(
        "allowlist,counted",
        [
            (None, False),
            (RuntimeError("flags down"), False),
            ("not json", True),
            ([], True),
            ({}, True),
            ({"models": [], "efforts": ["high"], "programs": ["integration"]}, True),
            ({"models": ["a"], "efforts": [], "programs": ["integration"]}, True),
            ({"models": ["a"], "efforts": ["high"], "programs": []}, True),
            ({"models": ["a"], "efforts": ["high"]}, True),
            ({"models": "a", "efforts": ["high"], "programs": ["integration"]}, True),
            ({"models": [7], "efforts": ["high"], "programs": ["integration"]}, True),
            ({"models": [" "], "efforts": ["high"], "programs": ["integration"]}, True),
            # Non-empty as saved, but empty once the mint strips the provider prefix.
            ({"models": ["gpt-x", "OpenAI/"], "efforts": ["high"], "programs": ["integration"]}, True),
            ({"models": ["a"], "efforts": ["extreme"], "programs": ["integration"]}, True),
            ({"models": ["a"], "efforts": ["high"], "programs": [""]}, True),
            # The gateway refuses more than 32 models, after it reads them in its own spelling.
            ({"models": [f"m{i}" for i in range(33)], "efforts": ["high"], "programs": ["integration"]}, True),
        ],
    )
    def test_an_unusable_allowlist_flag_falls_back_to_the_defaults(self, allowlist, counted):
        before = self._rejects("allowlist")
        with self._flags(allowlist=allowlist):
            policy = _policy()

        # All three lists fall back together, never a mix of flag and default.
        assert (policy.models, policy.efforts, policy.programs) == (
            WIZARD_DEFAULT_MODELS,
            WIZARD_DEFAULT_EFFORTS,
            WIZARD_DEFAULT_PROGRAMS,
        )
        # The prompt is read on its own and is untouched.
        assert policy.prompt is not None
        assert self._rejects("allowlist") == before + (1 if counted else 0)

    def test_a_mint_without_a_prompt_omits_the_prompt(self):
        unpinned = WizardGatewayPolicy(
            models=POLICY.models, efforts=POLICY.efforts, programs=POLICY.programs, prompt=None
        )
        minted = {"token": "phe_x", "expires_at": "2026-08-22T00:00:00Z"}
        with (
            override_settings(**MINT_SETTINGS),
            patch("posthog.llm.wizard_gateway_token.requests.post", return_value=_Response(201, minted)) as post,
        ):
            mint_wizard_gateway_token(obo="7", user="user_1", policy=unpinned)

        body = post.call_args.kwargs["json"]
        assert "system_prompt" not in body
        assert body["allowed_models"] == ["gpt-5.6-luna", "claude-sonnet-5"]


class TestWizardConfigRejectCounter:
    """A rejected settings value degrades the mint toward a floor, so every
    rejection leaves a counter an operator can alert on."""

    @staticmethod
    def _count(field: str) -> float:
        return WIZARD_GATEWAY_CONFIG_REJECTS.labels(field=field)._value.get()

    @override_settings(WIZARD_GATEWAY_TIERS={"new": {"cap_usd": "999", "mints_per_week": 0, "ttl_seconds": -1}})
    def test_each_rejected_tier_field_is_counted_on_its_own_label(self):
        fields = ("cap_usd", "mints_per_week", "ttl_seconds")
        before = {f: self._count(f) for f in fields}
        wizard_tier_limits("new")
        assert {f: self._count(f) for f in fields} == {f: before[f] + 1 for f in fields}

    @override_settings(WIZARD_GATEWAY_TIERS={"new": {"cap_usd": "5", "max_cap_usd": "3"}})
    def test_a_ceiling_under_its_own_cap_counts_apart_from_an_unreadable_one(self):
        before = self._count("max_cap_usd_below_cap")
        unreadable = self._count("max_cap_usd")
        wizard_tier_limits("new")
        assert self._count("max_cap_usd_below_cap") == before + 1
        assert self._count("max_cap_usd") == unreadable

    @override_settings(WIZARD_GATEWAY_TIERS={"new": {"cap_usd": "5"}})
    def test_a_readable_tier_counts_nothing(self):
        fields = ("cap_usd", "mints_per_week", "ttl_seconds", "max_cap_usd", "max_cap_usd_below_cap", "tiers_json")
        before = {f: self._count(f) for f in fields}
        wizard_tier_limits("new")
        assert {f: self._count(f) for f in fields} == before

    @override_settings(WIZARD_GATEWAY_TIERS={}, WIZARD_GATEWAY_TIERS_INVALID=True)
    def test_a_tier_map_unreadable_at_boot_is_counted_on_every_mint(self):
        # The empty dict cannot say whether the operator configured nothing or
        # configured something unparseable, which is why boot carries the flag.
        before = self._count("tiers_json")
        assert wizard_tier_limits("new") == _TIER_FLOORS["new"]
        assert self._count("tiers_json") == before + 1

    @override_settings(WIZARD_GATEWAY_TOKEN_CAP_USD_BY_PROGRAM={"broken": "lots"})
    def test_a_rejected_program_cap_is_counted(self):
        before = self._count("program_cap")
        assert wizard_program_cap("broken") is None
        assert self._count("program_cap") == before + 1

    @override_settings(WIZARD_GATEWAY_TOKEN_CAP_USD_BY_PROGRAM={}, WIZARD_GATEWAY_TOKEN_CAP_USD_BY_PROGRAM_INVALID=True)
    def test_a_program_cap_map_unreadable_at_boot_is_counted(self):
        before = self._count("program_caps_json")
        assert wizard_program_cap("self-driving") is None
        assert self._count("program_caps_json") == before + 1

    def test_an_override_payload_that_is_not_json_is_counted(self):
        before = self._count("override_payload")
        assert parse_limit_override("{not json") == NO_OVERRIDE
        assert self._count("override_payload") == before + 1

    def test_the_retired_daily_key_still_applies_and_is_counted(self):
        # The live override flag's payload still spells it mints_per_day, so
        # dropping the key outright would silently stop applying every override.
        before = self._count("mints_per_day_retired_key")
        assert parse_limit_override({"mints_per_day": 100}) == WizardLimitOverride(cap_usd=None, mints_per_week=100)
        assert self._count("mints_per_day_retired_key") == before + 1

    def test_the_weekly_key_wins_and_counts_no_retirement(self):
        before = self._count("mints_per_day_retired_key")
        assert parse_limit_override({"mints_per_week": 7, "mints_per_day": 100}) == WizardLimitOverride(
            cap_usd=None, mints_per_week=7
        )
        assert self._count("mints_per_day_retired_key") == before
