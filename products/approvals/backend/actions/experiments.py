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

    # An experiment owns its flag only once the experiment row exists, so a create mints an
    # unowned flag that this family never governs. Opting out only makes `detect` return before it
    # reads the organization's rollout state.
    gate_on_create = False

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        return {
            **super().get_display_data(intent_data),
            "description": f"Launch the experiment on feature flag '{intent_data.get('flag_key', 'unknown')}'",
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
            **super().get_display_data(intent_data),
            "description": f"Pause the experiment on feature flag '{intent_data.get('flag_key', 'unknown')}'",
        }


class UpdateExperimentAction(UpdateFeatureFlagAction):
    """Gate a change to how an experiment's traffic is split, including shipping a winner.

    Shipping a winning variant is a rollout change with a different button on it, so it belongs to
    this action rather than one of its own. The description says so, because "update" alone does
    not tell an approver that a request may hand one variant every user.
    """

    key = "experiment.update"
    version = 1
    description = "Change an experiment's rollout or variant split, or ship a winning variant"
    owner_scope = FLAG_OWNER_EXPERIMENT

    @classmethod
    def _display_subject(cls, flag_key: str, changed_fields: list[str]) -> str:
        return f"Change the rollout or variant split of the experiment on feature flag '{flag_key}'"
