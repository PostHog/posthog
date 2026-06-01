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

from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext

logger = logging.getLogger(__name__)


__all__ = ["seed_running_experiment", "ROLLOUT_EXPERIMENT_NAME"]


# Deterministic name referenced verbatim by the rollout-skill prompt so the
# agent's `experiment-list` / `experiment-get` calls can resolve the seeded
# experiment by name.
ROLLOUT_EXPERIMENT_NAME = "split test demo"


def seed_running_experiment(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed one running experiment with a 50/50 multivariate flag.

    Designed for prompts that ask the agent to change variant split on a
    *running* experiment — the canonical scenario the
    ``configuring-experiment-rollout`` skill exists to handle.
    """
    from posthog.models import FeatureFlag

    from products.experiments.backend.models.experiment import Experiment

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
