"""Approval actions for the flags an experiment owns.

An experiment drives its flag rather than being a separate resource to gate: launching writes
`active`, pausing clears it, and changing the split or shipping a winner rewrites the rollout.
Every one of those writes reaches `FeatureFlagSerializer`, so these actions gate the same writes
the `feature_flag.*` family gates and differ only in which flags they govern.

That is why they subclass the flag actions instead of restating them. Detection, intent, the
staleness checks and the apply path are the flag's; `owner_scope` is what makes this family see an
experiment's flags and the unowned family stop seeing them.

Gating the experiment endpoints instead would leave a hole. An experiment's flag edited through
the flags API matches neither family then: not `feature_flag.*`, which no longer covers it, and
not `experiment.*`, because no experiment endpoint was called.
"""

from typing import Any

from products.approvals.backend.actions.feature_flags import (
    DisableFeatureFlagAction,
    EnableFeatureFlagAction,
    UpdateFeatureFlagAction,
)
from products.feature_flags.backend.ownership import FLAG_OWNER_EXPERIMENT


class LaunchExperimentAction(EnableFeatureFlagAction):
    """Gate starting an experiment, whichever route starts it."""

    key = "experiment.launch"
    version = 1
    description = "Launch an experiment"
    owner_scope = FLAG_OWNER_EXPERIMENT

    # An experiment owns its flag only once the experiment row exists, so a flag born active
    # while its experiment is still being created is unowned at that instant and belongs to
    # `feature_flag.enable`. Opting out of the create path keeps that from reading as a gap here.
    gate_on_create = False

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "description": f"Launch the experiment on feature flag '{intent_data.get('flag_key', 'unknown')}'",
            "before": intent_data.get("current_state", {}),
            "after": intent_data.get("full_request_data") or intent_data.get("gated_changes", {}),
        }


class PauseExperimentAction(DisableFeatureFlagAction):
    """Gate pausing a running experiment, which stops its flag serving."""

    key = "experiment.pause"
    version = 1
    description = "Pause an experiment"
    owner_scope = FLAG_OWNER_EXPERIMENT

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "description": f"Pause the experiment on feature flag '{intent_data.get('flag_key', 'unknown')}'",
            "before": intent_data.get("current_state", {}),
            "after": intent_data.get("full_request_data") or intent_data.get("gated_changes", {}),
        }


class UpdateExperimentAction(UpdateFeatureFlagAction):
    """Gate a change to how an experiment's traffic is split, including shipping a winner.

    Shipping a winning variant is a rollout change with a different button on it, so it belongs to
    this action rather than one of its own. The description says so, because "update" alone does
    not tell an approver that a request may hand one variant every user.
    """

    key = "experiment.update"
    version = 1
    description = "Change an experiment's variant split, or ship a winning variant"
    owner_scope = FLAG_OWNER_EXPERIMENT

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        display = super().get_display_data(intent_data)
        flag_key = intent_data.get("flag_key", "unknown")
        description = f"Change the variant split of the experiment on feature flag '{flag_key}'"
        suffix = display["description"].split(":", 1)
        if len(suffix) == 2:
            description = f"{description}:{suffix[1]}"
        return {**display, "description": description}
