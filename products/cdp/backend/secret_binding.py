"""Whether a save may keep a stored secret where its config now sends it, shared by every API that
stores secret inputs."""

from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any, Optional

import posthoganalytics
from prometheus_client import Counter
from rest_framework import serializers

from products.cdp.backend.secret_origins import SecretOrigins
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
    WOULD_REFUSE = "would_refuse"


class SecretBindingMetric(StrEnum):
    BOUND = "bound"
    KEPT = "kept"
    REFUSED = "refused"
    # Refusals saved anyway because the flag is off, which the rollout reads to size enforcement.
    WOULD_REFUSE = "would_refuse"
    # Refusals in a staged draft, which publishing checks again.
    STAGED = "staged"


def binding_metric(outcome: SecretBinding, let_through: bool, stages_draft: bool) -> SecretBindingMetric:
    if not let_through:
        return SecretBindingMetric(outcome.value)
    return SecretBindingMetric.STAGED if stages_draft else SecretBindingMetric.WOULD_REFUSE


def comparable_inputs(items: Any) -> dict:
    return {
        key: (item.get("value"), item.get("templating") or "hog")
        for key, item in (items or {}).items()
        if isinstance(item, dict)
    }


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


def settle_secret_bindings(outcomes: Iterable[str], surface: str, refused: Mapping[str, Any]) -> None:
    """Count every secret the save bound, then fail the save when `refused`, the error detail of the
    secrets it refuses, is not empty. A refused secret the save lets through counts as `would_refuse`."""
    for outcome in outcomes:
        SECRET_HOST_BINDING_COUNTER.labels(outcome=outcome, surface=surface).inc()
    if refused:
        raise serializers.ValidationError(refused, code=SECRET_REENTRY_CODE)
