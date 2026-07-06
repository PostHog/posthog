"""Seeders for experiments-domain sandboxed eval cases.

Each seeder is a synchronous callable that runs in a worker thread (via
``asyncio.to_thread`` from ``base.py:task()``) and creates the entities
the prompt references inside the per-case team. Returns a dict that's
exposed to scorers as ``output["seed"]`` so deterministic scorers can
reference the seeded IDs without round-tripping through ``expected``.
"""

from __future__ import annotations

import uuid
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from products.tasks.backend.facade.agents import CustomPromptSandboxContext

logger = logging.getLogger(__name__)


__all__ = [
    "ROLLOUT_EXPERIMENT_NAME",
    "SHARED_METRIC_NAME",
    "SHARED_METRIC_EVENT",
    "UNEVEN_SPLIT_EXPERIMENT_NAME",
    "INACTIVE_FLAG_EXPERIMENT_NAME",
    "ENDED_EXPERIMENT_NAME",
    "SHIP_VARIANT_FLIP_SIGNATURE",
    "seed_running_experiment",
    "seed_shared_metric_purchase_count",
    "seed_uneven_split_experiment",
    "seed_inactive_flag_experiment",
    "seed_ended_experiment_with_flag_flip",
]


# Deterministic name referenced verbatim by the rollout-skill prompt so the
# agent's `experiment-list` / `experiment-get` calls can resolve the seeded
# experiment by name.
ROLLOUT_EXPERIMENT_NAME = "split test demo"
# Neutral product-flavored names — these MUST NOT hint at the diagnosis the
# agent is being asked to identify. Earlier names ("uneven split bias case",
# "stuck empty experiment") let the agent pattern-match on the experiment
# name; the rename forces the agent to actually inspect state via tools.
UNEVEN_SPLIT_EXPERIMENT_NAME = "homepage hero copy"
INACTIVE_FLAG_EXPERIMENT_NAME = "pricing page redesign"
ENDED_EXPERIMENT_NAME = "checkout cta v2"


# Verbatim string PostHog writes onto a feature flag's `properties[].description`
# when an experiment is shipped, see _transform_filters_for_winning_variant in
# ExperimentService
SHIP_VARIANT_FLIP_SIGNATURE = "Added automatically when the experiment was ended to keep only one variant."


def seed_running_experiment(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed one running experiment with a 50/50 multivariate flag.

    Designed for prompts that ask the agent to change variant split on a
    *running* experiment — the canonical scenario the
    ``configuring-experiment-rollout`` skill exists to handle.

    ⚠️ SHARED SEEDER — currently used by multiple eval cases and files.
    Any change to the returned state invalidates every dependent case simultaneously.
    If you need a variant of this state for one case, add a new seeder rather than
    parameterising this one — the eval framework passes only ``context`` to seeders, so
    case-specific config has to live in the seeder definition.
    """
    from products.experiments.backend.models.experiment import Experiment
    from products.feature_flags.backend.models.feature_flag import FeatureFlag

    team_id = context.team_id
    user_id = context.user_id

    flag = FeatureFlag.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        key=f"split-test-demo-{uuid.uuid4().hex[:6]}",
        name=f"{ROLLOUT_EXPERIMENT_NAME} flag",
        filters={
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 50},
                    {"key": "test", "name": "Test", "rollout_percentage": 50},
                ]
            },
        },
        active=True,
    )

    experiment = Experiment.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        name=ROLLOUT_EXPERIMENT_NAME,
        description="Seeded by eval — running experiment with 50/50 split.",
        feature_flag=flag,
        start_date=datetime.now(tz=UTC) - timedelta(days=7),
        end_date=None,
    )

    payload: dict[str, Any] = {
        "experiment_id": experiment.id,
        "experiment_name": experiment.name,
        "feature_flag_id": flag.id,
        "feature_flag_key": flag.key,
        "initial_split": {"control": 50, "test": 50},
    }
    logger.info(
        "Seeded running experiment for team_id=%s: experiment_id=%s flag_key=%s",
        team_id,
        experiment.id,
        flag.key,
    )
    return payload


def seed_uneven_split_experiment(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed a *running* experiment with an 80/20 multivariate split and the default
    ``multiple_variant_handling="exclude"``.

    Carrier scenario for diagnostic group A (bias & skew) — the agent should
    recognise that an 80/20 split combined with Exclude systematically removes
    overlap users from the smaller variant, biasing the test arm.
    """
    from products.experiments.backend.models.experiment import Experiment
    from products.feature_flags.backend.models.feature_flag import FeatureFlag

    team_id = context.team_id
    user_id = context.user_id

    flag = FeatureFlag.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        key=f"uneven-split-{uuid.uuid4().hex[:6]}",
        name=f"{UNEVEN_SPLIT_EXPERIMENT_NAME} flag",
        filters={
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 80},
                    {"key": "test", "name": "Test", "rollout_percentage": 20},
                ]
            },
        },
        active=True,
    )

    experiment = Experiment.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        name=UNEVEN_SPLIT_EXPERIMENT_NAME,
        description="Seeded by eval — 80/20 split, default exclude handling.",
        feature_flag=flag,
        start_date=datetime.now(tz=UTC) - timedelta(days=14),
        end_date=None,
    )

    return {
        "experiment_id": experiment.id,
        "experiment_name": experiment.name,
        "feature_flag_id": flag.id,
        "feature_flag_key": flag.key,
        "initial_split": {"control": 80, "test": 20},
    }


def seed_inactive_flag_experiment(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed a 'running' experiment whose feature flag is INACTIVE.

    Carrier scenario for diagnostic group B (empty experiment) — the agent
    should recognise that `feature_flag.active=False` means `$feature_flag_called`
    can never fire, so the exposure-shape snapshot will be empty and the
    diagnostic is B0 (flag inactive / experiment not actually live).
    """
    from products.experiments.backend.models.experiment import Experiment
    from products.feature_flags.backend.models.feature_flag import FeatureFlag

    team_id = context.team_id
    user_id = context.user_id

    flag = FeatureFlag.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        key=f"inactive-empty-{uuid.uuid4().hex[:6]}",
        name=f"{INACTIVE_FLAG_EXPERIMENT_NAME} flag",
        filters={
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 50},
                    {"key": "test", "name": "Test", "rollout_percentage": 50},
                ]
            },
        },
        # The diagnostic signature: experiment.start_date is set so the
        # experiment looks running, but the flag is off — exposures cannot fire.
        active=False,
    )

    experiment = Experiment.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        name=INACTIVE_FLAG_EXPERIMENT_NAME,
        description="Seeded by eval — experiment with start_date set but flag inactive.",
        feature_flag=flag,
        start_date=datetime.now(tz=UTC) - timedelta(days=3),
        end_date=None,
    )

    return {
        "experiment_id": experiment.id,
        "experiment_name": experiment.name,
        "feature_flag_id": flag.id,
        "feature_flag_key": flag.key,
        "flag_active": False,
    }


def seed_ended_experiment_with_flag_flip(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed a *stopped* experiment whose feature flag was rewritten by ship-variant.

    Carrier scenario for diagnostic group E (mid-run changes / E7) — after an
    experiment is ended via `experiment-ship-variant`, PostHog rewrites the
    flag's `multivariate.variants` rollout to 0/100 favouring the shipped
    variant AND attaches a verbatim description string ([SHIP_VARIANT_FLIP_SIGNATURE])
    to the new property entry.

    The skill's prescribed diagnostic path is to call
    ``feature-flags-activity-retrieve`` and scan for the verbatim signature in
    ``detail.changes[].after.groups[].properties[].description``. To make that
    path testable, this seeder writes an ``ActivityLog`` row with a synthetic
    "filters changed" diff that mirrors what the production ship-variant flow
    would emit — before-state is a 50/50 multivariate with no signature
    properties; after-state is the live 0/100 + signature filters payload.
    """
    from posthog.models.activity_logging.activity_log import ActivityLog, Change, Detail

    from products.experiments.backend.models.experiment import Experiment
    from products.feature_flags.backend.models.feature_flag import FeatureFlag

    team_id = context.team_id
    user_id = context.user_id

    before_filters: dict[str, Any] = {
        "groups": [{"properties": [], "rollout_percentage": 100}],
        "multivariate": {
            "variants": [
                {"key": "control", "name": "Control", "rollout_percentage": 50},
                {"key": "test", "name": "Test", "rollout_percentage": 50},
            ]
        },
    }
    after_filters: dict[str, Any] = {
        "groups": [
            {
                "properties": [
                    {
                        "key": "$feature_enrollment",
                        "type": "person",
                        "value": ["test"],
                        "description": SHIP_VARIANT_FLIP_SIGNATURE,
                    }
                ],
                "rollout_percentage": 100,
            }
        ],
        # Original 50/50 split was rewritten to 0/100 by ship-variant.
        "multivariate": {
            "variants": [
                {"key": "control", "name": "Control", "rollout_percentage": 0},
                {"key": "test", "name": "Test", "rollout_percentage": 100},
            ]
        },
    }

    flag = FeatureFlag.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        key=f"ship-flip-{uuid.uuid4().hex[:6]}",
        name=f"{ENDED_EXPERIMENT_NAME} flag",
        filters=after_filters,
        active=True,
    )

    experiment = Experiment.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        name=ENDED_EXPERIMENT_NAME,
        description="Seeded by eval — experiment ended via ship-variant; flag rewritten to 0/100.",
        feature_flag=flag,
        start_date=datetime.now(tz=UTC) - timedelta(days=30),
        end_date=datetime.now(tz=UTC) - timedelta(days=1),
    )

    # Write the synthetic ship-variant diff to the activity log so
    # `feature-flags-activity-retrieve` returns the real before/after payload
    # the skill instructs the agent to scan.
    # team_id alone satisfies the ActivityLog must-have-team-or-org check —
    # organization_id is optional and not exposed on CustomPromptSandboxContext.
    ActivityLog.objects.create(
        team_id=team_id,
        user_id=user_id,
        was_impersonated=False,
        is_system=False,
        item_id=str(flag.id),
        scope="FeatureFlag",
        activity="updated",
        detail=Detail(
            name=flag.key,
            changes=[
                Change(
                    type="FeatureFlag",
                    action="changed",
                    field="filters",
                    before=before_filters,
                    after=after_filters,
                ),
            ],
        ),
    )

    return {
        "experiment_id": experiment.id,
        "experiment_name": experiment.name,
        "feature_flag_id": flag.id,
        "feature_flag_key": flag.key,
        "final_split": {"control": 0, "test": 100},
        "signature": SHIP_VARIANT_FLIP_SIGNATURE,
    }


SHARED_METRIC_NAME = "purchase count per user"
SHARED_METRIC_EVENT = "purchase_completed"


def seed_shared_metric_purchase_count(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed one shared metric: mean count of purchase_completed per user, no filters."""
    from products.experiments.backend.models.experiment import ExperimentSavedMetric

    team_id = context.team_id
    user_id = context.user_id

    query = {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "source": {
            "kind": "EventsNode",
            "event": SHARED_METRIC_EVENT,
            "math": "total",
        },
        "uuid": str(uuid.uuid4()),
    }

    metric = ExperimentSavedMetric.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        name=SHARED_METRIC_NAME,
        description="Counts purchase_completed events per user.",
        query=query,
    )

    payload: dict[str, Any] = {
        "saved_metric_id": metric.id,
        "saved_metric_name": metric.name,
        "event": SHARED_METRIC_EVENT,
        "metric_type": "mean",
        "math": "total",
    }
    logger.info(
        "Seeded shared metric for team_id=%s: id=%s name=%s event=%s",
        team_id,
        metric.id,
        metric.name,
        SHARED_METRIC_EVENT,
    )
    return payload
