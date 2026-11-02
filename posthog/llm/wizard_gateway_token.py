"""Mint a wizard-run scoped gateway token.

Django mints a `phe_` off the PostHog-owned wizard team's `phs_`
(WIZARD_GATEWAY_MINT_KEY) rather than sending the user's OAuth token to the
gateway. The mint pins what the caller must not control (product=wizard, obo=the
customer's team id, the acting user) plus a per-run cap and an expiry, and the
debit lands on the wizard team, never the customer's wallet. Kept separate from
products/tasks' sandbox mint (ai_gateway_token.py): the wizard needs
`expires_at` back for CLI-side refresh, and an interactive mint answers one
attempt fast instead of retrying into the CLI's timeout.
"""

import json
import dataclasses
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from django.conf import settings
from django.utils import timezone

import requests
import structlog
import posthoganalytics
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.models.organization import Organization
from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

_MINT_TIMEOUT_SECONDS = 10

# The gateway refuses a TTL outside these bounds with a 400, so clamp locally: a
# misconfigured setting should not turn every mint into a 503.
# Well above the gateway's own 60s floor: a run's holders capture the bearer once
# and cannot re-resolve, so a token must outlive the whole run. Clamping to that
# floor would turn a misconfigured knob into mid-run 401s.
_MIN_TTL_SECONDS = 1800
_MAX_TTL_SECONDS = 86400

# A bad knob or payload falls back locally instead of 503ing every mint. The
# cap ceiling is a wizard-run backstop, well under the gateway's own.
_DEFAULT_CAP_USD = Decimal("7")
_MAX_CAP_USD = Decimal("30")
_CAP_QUANTUM = Decimal("0.000001")

WIZARD_PRODUCT = "wizard"

# The gateway's effort vocabulary, in order; the pin sent at mint is a subset.
WIZARD_EFFORT_LEVELS: tuple[str, ...] = ("none", "minimal", "low", "medium", "high", "xhigh", "max")

# pi sends the provider-prefixed id for OpenAI models; the gateway pins the bare model.
_STRIPPED_MODEL_PREFIXES = ("openai/",)


def normalize_model(model: str) -> str:
    normalized = model.strip().lower()
    for prefix in _STRIPPED_MODEL_PREFIXES:
        if normalized.startswith(prefix):
            return normalized[len(prefix) :]
    return normalized


# An organization's standing at mint time, which picks its tier of limits.
WizardPosture = Literal["new", "active", "paid"]
_NEW_ORGANIZATION_AGE = timedelta(days=7)

# Payload: {"cap_usd": "30", "mints_per_week": 100}. A person flag: email,
# organization_id, and team_id ride as person properties so one flag can target
# engineers by email and candidates by org id.
WIZARD_GATEWAY_LIMIT_OVERRIDE_FLAG = "wizard-gateway-limit-override"

# Above this a value only widens a fat-finger; the gateway's mint rate bounds the fleet.
_MAX_MINTS_PER_WEEK = 150


@frozen
class WizardLimitOverride:
    """Limits the override flag grants a user; None keeps the configured default."""

    cap_usd: Decimal | None = None
    mints_per_week: int | None = None


NO_OVERRIDE = WizardLimitOverride()


def _targeting_properties(*, email: str | None, organization_id: str, team_id: int) -> dict[str, str]:
    """The person properties every wizard flag read carries, so a flag can target by them."""
    return {"email": email or "", "organization_id": organization_id, "team_id": str(team_id)}


def wizard_limit_override(
    *, distinct_id: str, email: str | None, organization_id: str, team_id: int
) -> WizardLimitOverride:
    """Read the override flag for this mint; a flag outage fails closed to the defaults."""
    try:
        raw = posthoganalytics.get_feature_flag_payload(
            WIZARD_GATEWAY_LIMIT_OVERRIDE_FLAG,
            distinct_id,
            person_properties=_targeting_properties(email=email, organization_id=organization_id, team_id=team_id),
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception as e:
        logger.warning("wizard_gateway_token: limit override flag unavailable", error=str(e))
        return NO_OVERRIDE
    override = parse_limit_override(raw)
    if override != NO_OVERRIDE:
        logger.info(
            "wizard_gateway_token: limit override applied",
            team_id=team_id,
            cap_usd=str(override.cap_usd),
            mints_per_week=override.mints_per_week,
        )
    return override


def parse_limit_override(raw: object) -> WizardLimitOverride:
    """Validate field by field so a typo in one value cannot zero the other."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            logger.warning("wizard_gateway_token: limit override payload is not JSON")
            WIZARD_GATEWAY_CONFIG_REJECTS.labels(field="override_payload").inc()
            return NO_OVERRIDE
    if not isinstance(raw, dict):
        return NO_OVERRIDE
    cap, mints = _parse_limit_fields(raw, source="limit override")
    return WizardLimitOverride(cap_usd=cap, mints_per_week=mints)


def _parse_limit_fields(raw: dict, *, source: str) -> tuple[Decimal | None, int | None]:
    cap = _parse_cap(raw["cap_usd"]) if "cap_usd" in raw else None
    if "cap_usd" in raw and cap is None:
        logger.warning(f"wizard_gateway_token: {source} cap_usd out of contract, ignored", cap=str(raw["cap_usd"]))
        WIZARD_GATEWAY_CONFIG_REJECTS.labels(field="cap_usd").inc()
    # mints_per_day is the retired spelling and is still live in the override
    # flag's payload, so it is read until that payload is updated. Counted so the
    # fallback can be retired on evidence rather than on assumption.
    key = "mints_per_week" if "mints_per_week" in raw else "mints_per_day"
    if key == "mints_per_day" and key in raw:
        WIZARD_GATEWAY_CONFIG_REJECTS.labels(field="mints_per_day_retired_key").inc()
    mints = _parse_mints_per_week(raw[key]) if key in raw else None
    if key in raw and mints is None:
        logger.warning(
            f"wizard_gateway_token: {source} {key} out of contract, ignored",
            mints=str(raw[key]),
        )
        WIZARD_GATEWAY_CONFIG_REJECTS.labels(field="mints_per_week").inc()
    return cap, mints


# Two flags in the PostHog internal project, read for their payloads with the limit
# override's person properties for targeting. The payloads are {"version": 4,
# "text": "..."} (nothing reads the version) and {"models", "efforts", "programs"}.
# A flag that is off, missing, unreadable or out of contract never refuses a mint:
# no prompt mints unpinned, and no allowlist falls back to the defaults below. The
# prompt text goes to the gateway in the mint body and never to the wizard.
WIZARD_SYSTEM_PROMPT_FLAG = "wizard-ai-gateway-system-prompt"
WIZARD_GATEWAY_ALLOWLIST_FLAG = "wizard-gateway-allowlist"

# The wizard ends a run on the abort marker, so a prompt without it would give
# every token a prompt that run cannot end on.
_ABORT_MARKER = "[posthog:abort]"
# The gateway's own limits, mirrored so a payload it would refuse mints unpinned
# here instead of failing every mint. `canonicalSystemPrompt` (principal.ValidSystemPrompt)
# takes a non-empty string of at most 16384 bytes of valid UTF-8, and refuses U+FFFD, which
# its JSON decoder writes for invalid UTF-8. `canonicalModels` takes at most 32 models.
_MAX_PROMPT_BYTES = 16384
_MAX_ALLOWED_MODELS = 32

# What the allowlist falls back to: the pins the mint sent before the flag existed.
# The models are every one the wizard CLI dispatches (its *_MODEL constants in
# src/lib/constants.ts), so widen them here when one is added. The efforts are
# every one the CLI can declare; "max" is absent because the CLI cannot send it.
# The programs match the deploy's former WIZARD_GATEWAY_PROGRAM_IDS, so older wizards
# that mint for a tool keep working when the allowlist is unreadable.
WIZARD_DEFAULT_MODELS: tuple[str, ...] = (
    "claude-sonnet-5",
    "claude-haiku-4-5",
    "gpt-5.6-luna",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-6-luna",
    "gpt-6-sol",
)
WIZARD_DEFAULT_EFFORTS: tuple[str, ...] = ("none", "minimal", "low", "medium", "high", "xhigh")
WIZARD_DEFAULT_PROGRAMS: tuple[str, ...] = (
    "posthog-integration",
    "revenue-analytics-setup",
    "warehouse-source",
    "error-tracking-upload-source-maps",
    "error-tracking",
    "feature-flags",
    "audit",
    "events-audit",
    "posthog-doctor",
    "web-analytics-doctor",
    "migration",
    "self-driving",
    "agent-skill",
    "mcp-add",
    "mcp-remove",
    "mcp-tutorial",
    "mcp-analytics",
    "replay-vision",
    "ai-observability",
    "metrics",
    "slack",
)


@frozen
class WizardSystemPrompt:
    """The operator prompt a token carries. `text` goes to the gateway only, in
    the mint body, and is never logged or returned to the wizard."""

    text: str = dataclasses.field(repr=False)


@frozen
class WizardGatewayPolicy:
    """What one mint pins, read from the two flags. `prompt` is None when the
    prompt flag is off or unusable, and the token is then minted unpinned."""

    models: tuple[str, ...]
    efforts: tuple[str, ...]
    programs: tuple[str, ...]
    prompt: WizardSystemPrompt | None


def wizard_gateway_policy(
    *, distinct_id: str, email: str | None, organization_id: str, team_id: int
) -> WizardGatewayPolicy:
    """Read both policy flags once. Never raises: an unreadable or invalid flag
    degrades that half of the policy and leaves the other alone. The allowlist sees
    the same person properties as the limit override, so it can be targeted."""
    properties = _targeting_properties(email=email, organization_id=organization_id, team_id=team_id)
    prompt_raw = _policy_payload(
        # Local evaluation only, so the prompt read adds no network time to the mint.
        lambda: posthoganalytics.get_feature_flag_payload(
            WIZARD_SYSTEM_PROMPT_FLAG,
            distinct_id,
            person_properties=properties,
            only_evaluate_locally=True,
            send_feature_flag_events=True,
        ),
        source="system prompt",
        field="system_prompt",
    )
    allowlist_raw = _policy_payload(
        lambda: posthoganalytics.get_feature_flag_payload(
            WIZARD_GATEWAY_ALLOWLIST_FLAG,
            distinct_id,
            person_properties=properties,
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        ),
        source="allowlist",
        field="allowlist",
    )
    prompt = _parse_system_prompt(prompt_raw) if prompt_raw is not None else None
    allowlist = _parse_allowlist(allowlist_raw) if allowlist_raw is not None else None
    allowlist = allowlist or _Allowlist(
        models=WIZARD_DEFAULT_MODELS, efforts=WIZARD_DEFAULT_EFFORTS, programs=WIZARD_DEFAULT_PROGRAMS
    )
    return WizardGatewayPolicy(
        models=allowlist.models, efforts=allowlist.efforts, programs=allowlist.programs, prompt=prompt
    )


def _policy_payload(read: Callable[[], object], *, source: str, field: str) -> dict | None:
    """The flag's payload object, or None when it is off, unreadable, or not an object."""
    try:
        raw = read()
    except Exception as e:
        logger.warning(f"wizard_gateway_token: {source} flag unavailable", error=str(e))
        return None
    if raw is None:
        # The SDK swallows its own errors and returns None, so an outage looks the
        # same as a flag with no payload: say so, as the rollout flag read does.
        logger.warning(f"wizard_gateway_token: {source} flag returned no payload")
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            logger.warning(f"wizard_gateway_token: {source} payload is not JSON")
            WIZARD_GATEWAY_CONFIG_REJECTS.labels(field=field).inc()
            return None
    if not isinstance(raw, dict):
        logger.warning(f"wizard_gateway_token: {source} payload out of contract, ignored")
        WIZARD_GATEWAY_CONFIG_REJECTS.labels(field=field).inc()
        return None
    return raw


def _parse_system_prompt(raw: dict) -> WizardSystemPrompt | None:
    # The payload may carry a `version` for the operator's own bookkeeping. Nothing reads it.
    text = raw.get("text")
    if not isinstance(text, str) or not text or _ABORT_MARKER not in text:
        _reject_system_prompt("text must be non-empty and hold the abort marker")
        return None
    # A lone surrogate is a str Python cannot encode, and U+FFFD is what the gateway's
    # decoder makes of invalid UTF-8, so the gateway refuses both.
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        _reject_system_prompt("text is not valid UTF-8")
        return None
    if "\ufffd" in text:
        _reject_system_prompt("text holds U+FFFD")
        return None
    if size > _MAX_PROMPT_BYTES:
        _reject_system_prompt(f"text is over {_MAX_PROMPT_BYTES} bytes")
        return None
    return WizardSystemPrompt(text=text)


def _reject_system_prompt(problem: str) -> None:
    logger.warning("wizard_gateway_token: system prompt out of contract, ignored", problem=problem)
    WIZARD_GATEWAY_CONFIG_REJECTS.labels(field="system_prompt").inc()


@frozen
class _Allowlist:
    models: tuple[str, ...]
    efforts: tuple[str, ...]
    programs: tuple[str, ...]


def _parse_allowlist(raw: dict) -> _Allowlist | None:
    """All three lists or none: a half-applied allowlist would pin a mix nobody wrote."""
    try:
        models = _string_list(raw, "models")
        efforts = _string_list(raw, "efforts")
        programs = _string_list(raw, "programs")
        if not set(efforts) <= set(WIZARD_EFFORT_LEVELS):
            raise ValueError("efforts outside the gateway vocabulary")
        # Checked in the gateway's spelling, which the mint sends: "openai/" becomes an empty id.
        pinned = {normalize_model(model) for model in models}
        if not all(pinned):
            raise ValueError("models must hold a model id after the provider prefix")
        if len(pinned) > _MAX_ALLOWED_MODELS:
            raise ValueError(f"models is over {_MAX_ALLOWED_MODELS} entries")
    except ValueError as e:
        logger.warning("wizard_gateway_token: allowlist out of contract, ignored", problem=str(e))
        WIZARD_GATEWAY_CONFIG_REJECTS.labels(field="allowlist").inc()
        return None
    # Vocabulary order, so the pin reads the same whatever order the payload used.
    return _Allowlist(
        models=models, efforts=tuple(level for level in WIZARD_EFFORT_LEVELS if level in efforts), programs=programs
    )


def _string_list(payload: dict, key: str) -> tuple[str, ...]:
    values = payload.get(key)
    if not isinstance(values, list) or not values:
        raise ValueError(f"{key} must be a non-empty list")
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ValueError(f"{key} must hold only non-empty strings")
    # Stored stripped, as validated: an id saved as "audit " must match "audit".
    return tuple(dict.fromkeys(value.strip() for value in values))


@frozen
class WizardTierLimits:
    """`cap_usd` applies to a program with no entry of its own; a program with
    one replaces it, up to `max_cap_usd`."""

    cap_usd: Decimal | None = None
    max_cap_usd: Decimal | None = None
    mints_per_week: int | None = None
    ttl_seconds: int | None = None


NO_TIER_LIMITS = WizardTierLimits()

# In code so a malformed WIZARD_GATEWAY_TIERS degrades toward the tier the
# operator meant, not toward the flat setting, whose cap is wider than all three.
# Caps do not pool across a run's tokens and the mint throttle is one bucket per
# account, so mints_per_week is the hard per-account ceiling: keep the counts
# low, since the weekly window can be spent in a day.
_TIER_FLOORS: dict[str, WizardTierLimits] = {
    "new": WizardTierLimits(
        cap_usd=Decimal("6").quantize(_CAP_QUANTUM),
        max_cap_usd=Decimal("6").quantize(_CAP_QUANTUM),
        mints_per_week=3,
        ttl_seconds=_MAX_TTL_SECONDS,
    ),
    "active": WizardTierLimits(
        cap_usd=Decimal("7").quantize(_CAP_QUANTUM),
        max_cap_usd=Decimal("12").quantize(_CAP_QUANTUM),
        mints_per_week=6,
        ttl_seconds=_MAX_TTL_SECONDS,
    ),
    "paid": WizardTierLimits(
        cap_usd=Decimal("10").quantize(_CAP_QUANTUM),
        max_cap_usd=Decimal("12").quantize(_CAP_QUANTUM),
        mints_per_week=12,
        ttl_seconds=_MAX_TTL_SECONDS,
    ),
}


def wizard_posture(organization: Organization, team: Team) -> WizardPosture:
    """`paid` outranks the rest, then anything that has ingested is `active`, and
    only a young organization with no event is `new`. Reads cached fields only.

    Billing's own subscription flag decides `paid`, because a cancelled organization
    keeps its feature list and the feature-derived plan tier would go on handing it
    the widest limits. A NULL flag never synced, so it falls back to that tier.
    """
    subscribed = organization.has_active_subscription
    if subscribed if subscribed is not None else organization.get_plan_tier() != "free":
        return "paid"
    if team.ingested_event:
        return "active"
    if organization.created_at is not None and organization.created_at > timezone.now() - _NEW_ORGANIZATION_AGE:
        return "new"
    return "active"


def wizard_tier_limits(posture: WizardPosture) -> WizardTierLimits:
    """The tier for a posture, each field validated on its own and each falling
    back to that posture's floor rather than to the flat setting."""
    floor = _TIER_FLOORS[posture]
    if getattr(settings, "WIZARD_GATEWAY_TIERS_INVALID", False):
        # Boot parsed the whole map away, so every posture silently takes its floor.
        WIZARD_GATEWAY_CONFIG_REJECTS.labels(field="tiers_json").inc()
    tiers = settings.WIZARD_GATEWAY_TIERS
    raw = tiers.get(posture) if isinstance(tiers, dict) else None
    if not isinstance(raw, dict):
        return floor
    cap, mints = _parse_limit_fields(raw, source=f"{posture} tier")
    max_cap = _parse_cap(raw["max_cap_usd"]) if "max_cap_usd" in raw else None
    if "max_cap_usd" in raw and max_cap is None:
        logger.warning(
            f"wizard_gateway_token: {posture} tier max_cap_usd out of contract, ignored",
            max_cap_usd=str(raw["max_cap_usd"]),
        )
        WIZARD_GATEWAY_CONFIG_REJECTS.labels(field="max_cap_usd").inc()
    if max_cap is not None and cap is not None and max_cap < cap:
        # An entry whose ceiling sits under its own cap would let a program tighten
        # rather than size. Ignored rather than absorbed, so the operator sees it.
        logger.warning(
            f"wizard_gateway_token: {posture} tier max_cap_usd below cap_usd, ignored",
            max_cap_usd=str(max_cap),
            cap_usd=str(cap),
        )
        WIZARD_GATEWAY_CONFIG_REJECTS.labels(field="max_cap_usd_below_cap").inc()
        max_cap = None
    ttl = _parse_ttl(raw["ttl_seconds"]) if "ttl_seconds" in raw else None
    if "ttl_seconds" in raw and ttl is None:
        logger.warning(
            f"wizard_gateway_token: {posture} tier ttl_seconds out of contract, ignored", ttl=str(raw["ttl_seconds"])
        )
        WIZARD_GATEWAY_CONFIG_REJECTS.labels(field="ttl_seconds").inc()
    return WizardTierLimits(
        cap_usd=cap if cap is not None else floor.cap_usd,
        max_cap_usd=max_cap if max_cap is not None else floor.max_cap_usd,
        mints_per_week=mints if mints is not None else floor.mints_per_week,
        ttl_seconds=ttl if ttl is not None else floor.ttl_seconds,
    )


def wizard_program_cap(program: object) -> Decimal | None:
    """A per-program cap from WIZARD_GATEWAY_TOKEN_CAP_USD_BY_PROGRAM, keyed on the
    program id the CLI sent; None when the program has no usable entry."""
    if getattr(settings, "WIZARD_GATEWAY_TOKEN_CAP_USD_BY_PROGRAM_INVALID", False):
        # Boot parsed the map away, so no program can carry its own cap.
        WIZARD_GATEWAY_CONFIG_REJECTS.labels(field="program_caps_json").inc()
    caps = settings.WIZARD_GATEWAY_TOKEN_CAP_USD_BY_PROGRAM
    if not isinstance(program, str) or not isinstance(caps, dict) or program not in caps:
        return None
    cap = _parse_cap(caps[program])
    if cap is None:
        logger.warning("wizard_gateway_token: program cap out of contract, ignored", program=program)
        WIZARD_GATEWAY_CONFIG_REJECTS.labels(field="program_cap").inc()
    return cap


def _parse_ttl(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, str) and raw.strip().isdigit():
        raw = int(raw)
    if not isinstance(raw, int) or raw < 1:
        return None
    return raw


def _parse_mints_per_week(raw: object) -> int | None:
    # bool is an int subclass: True would read as one mint a week.
    if isinstance(raw, bool):
        return None
    if isinstance(raw, str) and raw.strip().isdigit():
        raw = int(raw)
    if not isinstance(raw, int) or raw < 1 or raw > _MAX_MINTS_PER_WEEK:
        return None
    return raw


def wizard_product_node(program: object, policy: WizardGatewayPolicy) -> str | None:
    """The product node to pin for a run, or None when this is not a program
    the allowlist flag lists.

    The flag is authoritative: an unrecognized program is refused rather than
    folded into a generic node. Gateway budgets match a node value exactly, so
    folding would report a new program's spend as plain wizard spend and leave the
    program itself with no budget of its own, and the drift would be silent.
    A refusal ends the run with an upgrade message and shows in the mint outcome
    counter as `program_unknown`; a new program is registered in the CLI, the
    allowlist flag, and a budget row.
    """
    # isinstance first: the value is caller JSON, and a list or object is not a program id.
    if isinstance(program, str) and program in policy.programs:
        return f"{WIZARD_PRODUCT}:{program}"
    return None


WIZARD_GATEWAY_MINTS = Counter(
    "posthog_wizard_gateway_token_mints_total",
    "Wizard gateway token mints, by outcome (ok/refused/unreachable/malformed)",
    labelnames=["outcome"],
)

# A rejected value degrades the mint quietly toward a floor, so the warning alone
# gives nothing to alert on. Labelled by field, never by the rejected value.
WIZARD_GATEWAY_CONFIG_REJECTS = Counter(
    "posthog_wizard_gateway_config_rejects_total",
    "Wizard gateway settings values rejected as out of contract, by field",
    labelnames=["field"],
)


class WizardGatewayMintError(Exception):
    """The gateway refused or failed the mint; the caller answers 503.

    token_may_exist is False only when the failure proves no token was issued,
    so the caller can return the daily mint slot. It defaults True: refunding a
    slot for a token the gateway did mint would let the ceiling be exceeded.
    """

    def __init__(self, message: str, *, token_may_exist: bool = True) -> None:
        super().__init__(message)
        self.token_may_exist = token_may_exist


def wizard_gateway_configured() -> bool:
    """Every one of the three is required; any missing piece refuses every mint
    as `unconfigured`."""
    return bool(settings.WIZARD_GATEWAY_MINT_KEY and settings.WIZARD_GATEWAY_URL and settings.WIZARD_GATEWAY_CLIENT_IDS)


def wizard_gateway_base_url() -> str:
    """The gateway base returned to the CLI, without the version segment."""
    return settings.WIZARD_GATEWAY_URL.rstrip("/").removesuffix("/v1")


def mint_wizard_gateway_token(
    *,
    obo: str,
    user: str,
    policy: WizardGatewayPolicy,
    product: str = WIZARD_PRODUCT,
    cap_usd: Decimal | None = None,
    program: object = None,
    posture: WizardPosture | None = None,
) -> dict[str, Any]:
    """Mint one run's token; returns {token, expires_at, cap_usd}. Raises
    WizardGatewayMintError on any refusal or transport failure; the bearer never
    appears in logs or exception text. `cap_usd`, when set, outranks every
    configured cap and must already be validated; otherwise the program's cap
    bounded by the posture's ceiling, then the posture's own, then the flat
    setting, which applies only when there is no posture.
    """
    base_url = (settings.WIZARD_GATEWAY_MINT_URL or settings.WIZARD_GATEWAY_URL).rstrip("/").removesuffix("/v1")
    body: dict[str, Any] = {
        "cap_usd": _cap_usd(cap_usd, program=program, posture=posture),
        "ttl_seconds": _ttl_seconds(posture),
        "product": product,
        "obo": obo,
        "user": user,
        # A gateway that predates a pin ignores it and mints unpinned.
        "allowed_models": list(dict.fromkeys(normalize_model(model) for model in policy.models)),
        "allowed_efforts": list(policy.efforts),
    }
    if policy.prompt is not None:
        # The gateway stores the text on the token and injects it into every call.
        body["system_prompt"] = policy.prompt.text
    try:
        response = requests.post(
            f"{base_url}/v1/tokens",
            json=body,
            headers={"Authorization": f"Bearer {settings.WIZARD_GATEWAY_MINT_KEY}"},
            timeout=_MINT_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        WIZARD_GATEWAY_MINTS.labels(outcome="unreachable").inc()
        logger.warning("wizard_gateway_token: mint transport failure", error=str(e))
        # Only a failure after the request was transmitted can leave a token behind.
        # URL and schema errors raise before any byte is sent, and a connect-level
        # failure never established the session; ConnectTimeout subclasses
        # ConnectionError, while a ReadTimeout's request may have landed.
        #
        # Not a clean split: requests re-raises a body-phase read timeout as
        # ConnectionError, so that case refunds despite the request landing. The
        # token it may leave behind is never delivered, and a cap is a ceiling
        # rather than a reservation, so an unheld token spends nothing.
        never_sent = isinstance(
            e,
            (
                requests.exceptions.ConnectionError,
                requests.exceptions.URLRequired,
                requests.exceptions.MissingSchema,
                requests.exceptions.InvalidSchema,
                requests.exceptions.InvalidURL,
            ),
        )
        raise WizardGatewayMintError("gateway unreachable", token_may_exist=not never_sent) from e

    if response.status_code != 201:
        WIZARD_GATEWAY_MINTS.labels(outcome="refused").inc()
        logger.warning("wizard_gateway_token: mint refused", status=response.status_code)
        # The gateway answered and refused, so no token was issued.
        raise WizardGatewayMintError(f"mint refused with HTTP {response.status_code}", token_may_exist=False)
    try:
        minted = response.json()
    except ValueError as e:
        WIZARD_GATEWAY_MINTS.labels(outcome="malformed").inc()
        raise WizardGatewayMintError("mint response was not JSON") from e
    if not isinstance(minted, dict) or not minted.get("token") or not minted.get("expires_at"):
        WIZARD_GATEWAY_MINTS.labels(outcome="malformed").inc()
        raise WizardGatewayMintError("mint response missing token or expires_at")
    WIZARD_GATEWAY_MINTS.labels(outcome="ok").inc()
    return {
        "token": minted["token"],
        "expires_at": minted["expires_at"],
        "cap_usd": minted.get("cap_usd"),
    }


def _ttl_seconds(posture: WizardPosture | None) -> int:
    """The requested token lifetime, clamped to the gateway's mint bounds."""
    ttl = wizard_tier_limits(posture).ttl_seconds if posture is not None else None
    if ttl is None:
        ttl = int(settings.WIZARD_GATEWAY_TOKEN_TTL_SECONDS)
    return max(_MIN_TTL_SECONDS, min(ttl, _MAX_TTL_SECONDS))


def _cap_usd(override: Decimal | None, *, program: object, posture: WizardPosture | None) -> str:
    """The cap as a fixed-point string: the override, then the program's cap
    bounded by the posture's ceiling, then the posture's, then the flat setting.

    program is a caller-supplied body field, so the program cap only applies
    inside a posture; with no posture there is no ceiling to bound it and it is
    ignored, or an account would set its own cap by naming the priciest program.
    """
    if override is not None:
        return f"{override.quantize(_CAP_QUANTUM):f}"
    if posture is None:
        cap = None
    else:
        tier = wizard_tier_limits(posture)
        cap = wizard_program_cap(program)
        if cap is not None:
            ceiling = tier.max_cap_usd if tier.max_cap_usd is not None else tier.cap_usd
            if ceiling is not None:
                cap = min(cap, ceiling)
        if cap is None:
            cap = tier.cap_usd
    if cap is None:
        raw = str(settings.WIZARD_GATEWAY_TOKEN_CAP_USD)
        cap = _parse_cap(raw)
        if cap is None:
            logger.warning("wizard_gateway_token: cap_usd out of contract, using the default", cap=raw)
            WIZARD_GATEWAY_CONFIG_REJECTS.labels(field="flat_cap_usd").inc()
            cap = _DEFAULT_CAP_USD
    return f"{cap.quantize(_CAP_QUANTUM):f}"


def _parse_cap(raw: object) -> Decimal | None:
    """A cap inside the gateway's contract, quantized to 6dp, or None. Quantize
    before the range check (a sub-microdollar value rounds to 0, which the gateway
    rejects) and guard it: quantize raises past the decimal context's precision.
    """
    if isinstance(raw, bool):
        return None
    try:
        cap = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    if not cap.is_finite():
        return None
    try:
        cap = cap.quantize(_CAP_QUANTUM)
    except InvalidOperation:
        return None
    if cap <= 0 or cap > _MAX_CAP_USD:
        return None
    return cap
