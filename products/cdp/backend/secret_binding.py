"""Whether a save may keep a stored secret where its config now sends it, shared by every API that
stores secret inputs."""

from collections.abc import Iterable, Mapping
from dataclasses import field
from enum import StrEnum
from typing import Any, Optional

import posthoganalytics
from prometheus_client import Counter
from rest_framework import serializers

from posthog.dataclasses import frozen

from products.cdp.backend.secret_origins import SecretOrigins, mapping_inputs, secret_origins, stored_origins
from products.cdp.backend.validation import MASKED_SECRET_VALUE

SECRET_HOST_BINDING_FLAG = "cdp-secret-host-binding"
SECRET_REENTRY_MESSAGE = "This change would send the secret to a new address. Enter the secret again to confirm."
SECRET_REENTRY_CODE = "secret_reentry_required"
SECRET_HOST_BINDING_COUNTER = Counter(
    "posthog_cdp_secret_host_binding_total",
    "Secret inputs saved with the origins they may be sent to, by outcome and by the API surface that saved them.",
    labelnames=["outcome", "surface"],
)


class SecretBinding(StrEnum):
    BOUND = "bound"
    KEPT = "kept"
    REFUSED = "refused"


@frozen
class SecretConfig:
    """What decides where a config sends its secrets."""

    code: str
    inputs: dict[str, Any] = field(repr=False)
    mappings: Any = field(repr=False)
    # Anything else the code reads that can change an address, such as workflow variables. Compared
    # for equality only.
    context: Any = None


class SecretBindingMetric(StrEnum):
    BOUND = "bound"
    KEPT = "kept"
    REFUSED = "refused"
    # Refusals saved anyway because the flag is off, which the rollout reads to size enforcement.
    WOULD_REFUSE = "would_refuse"
    # Refusals in a staged draft, which publishing checks again.
    STAGED = "staged"


def _binding_metric(outcome: str, let_through: bool, stages_draft: bool) -> SecretBindingMetric:
    if not let_through:
        return SecretBindingMetric(outcome)
    return SecretBindingMetric.STAGED if stages_draft else SecretBindingMetric.WOULD_REFUSE


def comparable_inputs(items: Any) -> dict:
    return {
        key: (item.get("value"), item.get("templating") or "hog")
        for key, item in (items or {}).items()
        if isinstance(item, dict)
    }


def _comparable_config(config: SecretConfig, secret_keys: set[str]) -> tuple:
    """The parts of `config` that decide where its secrets go, without the secret values."""
    public_inputs = {key: item for key, item in config.inputs.items() if key not in secret_keys}
    return (
        config.code,
        comparable_inputs(public_inputs),
        [comparable_inputs(items) for items in mapping_inputs(config.mappings)],
        config.context,
    )


def unchanged_secrets(
    config: SecretConfig, stored: SecretConfig, secret_keys: set[str], derived: Mapping[str, SecretOrigins]
) -> set[str]:
    """The secrets in `derived` that `config` sends where `stored` sends them. `secret_keys` names every
    secret input of the config. A secret's own value is compared because a dictionary secret can hold
    the address it is sent to."""
    if _comparable_config(config, secret_keys) != _comparable_config(stored, secret_keys):
        return set()
    moved = {
        key
        for key in secret_keys
        if comparable_inputs({key: config.inputs.get(key)}) != comparable_inputs({key: stored.inputs.get(key)})
    }
    kept = set(derived) - moved
    if not moved or not kept:
        return kept
    with_stored = {key: item for key, item in config.inputs.items() if key not in moved}
    with_stored.update({key: stored.inputs[key] for key in moved if key in stored.inputs})
    restored = secret_origins(config.code, with_stored, mapping_inputs(config.mappings), kept)
    return {key for key in kept if restored[key] == derived[key]}


def entered_secret_input_keys(raw_inputs: Any) -> set[str]:
    """Input keys whose request value replaces the stored secret. A dictionary secret sent with some
    entries still masked keeps those stored entries, so it does not count as entered."""
    if not isinstance(raw_inputs, dict):
        return set()
    return {
        key
        for key, item in raw_inputs.items()
        if isinstance(item, dict)
        and "value" in item
        and item["value"] != MASKED_SECRET_VALUE
        and not (isinstance(item["value"], dict) and MASKED_SECRET_VALUE in item["value"].values())
    }


def secret_binding(
    derived: SecretOrigins, baseline: Optional[SecretOrigins], entered: bool, unchanged: bool
) -> tuple[SecretOrigins, SecretBinding]:
    """The origins a secret may be sent to after a save, and whether the save binds, keeps or is
    refused. A secret with no baseline is new, so it binds like an entered one."""
    if entered or baseline is None:
        return derived, SecretBinding.BOUND
    sends_within = isinstance(derived, frozenset) and isinstance(baseline, frozenset) and derived <= baseline
    return baseline, SecretBinding.KEPT if unchanged or sends_within else SecretBinding.REFUSED


def entry_with_origins(
    entry: dict[str, Any],
    origins: SecretOrigins,
    outcome: SecretBinding,
    derived: SecretOrigins,
    *,
    staged: bool,
    staged_keeps_origins: bool,
) -> dict[str, Any]:
    """`entry` with the origins a write stores for it. A refused secret reaches storage only when the save
    lets it through. A live write then records where the code now sends it. A staged write keeps
    `origins` when `staged_keeps_origins`, and otherwise stores none, so that publishing compares the
    secret with the live config again."""
    updated = {key: value for key, value in entry.items() if key != "allowed_origins"}
    if outcome != SecretBinding.REFUSED:
        updated["allowed_origins"] = stored_origins(origins)
    elif not staged:
        updated["allowed_origins"] = stored_origins(derived)
    elif staged_keeps_origins:
        updated["allowed_origins"] = stored_origins(origins)
    return updated


def secret_binding_enforced(context: Mapping[str, Any]) -> bool:
    """Whether a refused secret fails the save that `context` validates. Only a request fails: a caller
    with no view, such as a management command, re-saves what someone already stored. A request fails
    only while the flag is on for its team."""
    if context.get("view") is None:
        return False
    team = context["get_team"]()
    return bool(
        posthoganalytics.feature_enabled(
            SECRET_HOST_BINDING_FLAG,
            str(team.uuid),
            groups={"organization": str(team.organization_id)},
            send_feature_flag_events=False,
        )
    )


def secret_reentry_errors(keys: Iterable[str]) -> dict[str, str]:
    return dict.fromkeys(keys, SECRET_REENTRY_MESSAGE)


def settle_secret_bindings(
    outcomes: Iterable[str],
    surface: str,
    refused_detail: Mapping[str, Any],
    enforce: bool,
    stages_draft: bool = False,
) -> None:
    """Count every secret the save bound, and fail the save with `refused_detail` when `enforce`."""
    for outcome in outcomes:
        let_through = outcome == SecretBinding.REFUSED and not enforce
        SECRET_HOST_BINDING_COUNTER.labels(
            outcome=_binding_metric(outcome, let_through, stages_draft), surface=surface
        ).inc()
    if enforce and refused_detail:
        raise serializers.ValidationError(refused_detail, code=SECRET_REENTRY_CODE)
