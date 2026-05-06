"""Per-case seeder hooks for the error-tracking sandboxed evals.

Hedgebox already creates three deterministic ``ErrorTrackingIssue`` rows
on every per-case team via ``HedgeboxMatrix.set_project_up`` (see
``posthog/demo/products/hedgebox/matrix.py:_set_up_error_tracking_demo_data``).
This seeder doesn't insert anything new — it just looks the rows up and
returns their per-case UUIDs so scorers can resolve a prompt's named
issue (e.g. "Checkout API timeout") back to the concrete UUID the agent
should pass as ``issueId``.

Returned dict is merged into the task output under ``seed`` by
``base.py:task()`` so scorers reach it via ``output["seed"]``.
"""

from __future__ import annotations

import logging
from typing import Any

from products.tasks.backend.services.custom_prompt_internals import CustomPromptSandboxContext

logger = logging.getLogger(__name__)


__all__ = ["HEDGEBOX_ISSUE_NAMES", "seed_error_tracking_lookup"]


# Names match those defined in `_set_up_error_tracking_demo_data` in
# `posthog/demo/products/hedgebox/matrix.py`. Kept in sync manually because
# the demo module already encodes them as bare string literals — importing
# them would couple this module to the demo entrypoint without much benefit.
HEDGEBOX_ISSUE_NAMES: tuple[str, ...] = (
    "Checkout API timeout",
    "File preview render failure",
    "Team invite rejected",
)


def seed_error_tracking_lookup(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Resolve the Hedgebox-seeded error-tracking issues for the per-case team.

    Returns ``{"lookup_issues": [{"id": <uuid_str>, "name": <name>}, ...]}``.
    Synchronous — runs in a worker thread via ``asyncio.to_thread`` from
    ``base.py:task()``.
    """
    from products.error_tracking.backend.models import ErrorTrackingIssue

    issues = list(
        ErrorTrackingIssue.objects.filter(
            team_id=context.team_id,
            name__in=list(HEDGEBOX_ISSUE_NAMES),
        ).values("id", "name")
    )
    payload: dict[str, Any] = {
        "lookup_issues": [{"id": str(row["id"]), "name": row["name"]} for row in issues],
    }
    logger.info(
        "Resolved %d Hedgebox error-tracking issues for team_id=%s",
        len(payload["lookup_issues"]),
        context.team_id,
    )
    return payload
