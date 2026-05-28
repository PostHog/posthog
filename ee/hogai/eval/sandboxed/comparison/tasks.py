"""Interface-neutral tasks for the comparison.

Prompts must NOT mention "CLI" or "MCP" — each arm uses its own native discovery
(MCP advertises tools via the protocol; the CLI is advertised via the AGENTS.md
steering block). Each task carries a deterministic outcome check (asserted against
the per-case team's DB state) and a one-line summary the LLM-judge grades against.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

FLAG_KEY = "cmp-eval-flag"


@dataclass
class ComparisonTask:
    name: str
    prompt: str
    expected_summary: str
    """One-line description of the goal state, for the LLM-judge rubric."""
    outcome_check: Callable[[int], bool]
    """Deterministic pass/fail given the case's ``team_id`` (checks real DB state)."""


def _feature_flag_created(team_id: int) -> bool:
    # Imported lazily: a module-level posthog.models import runs at pytest collection time,
    # before the Django app registry is ready, and fails with a partial-init ImportError.
    from posthog.models import FeatureFlag

    return FeatureFlag.objects.filter(team_id=team_id, key=FLAG_KEY, deleted=False).exists()


# Spike: one task with a clean, arm-agnostic DB outcome. Expand to ~6 once the
# orchestration is validated end to end.
TASKS: tuple[ComparisonTask, ...] = (
    ComparisonTask(
        name="create_feature_flag",
        prompt=(
            f"Create a feature flag in this PostHog project with key `{FLAG_KEY}`, "
            'named "Comparison Eval Flag", that is disabled (not active).'
        ),
        expected_summary=f"A feature flag with key '{FLAG_KEY}' exists in the project.",
        outcome_check=_feature_flag_created,
    ),
)
