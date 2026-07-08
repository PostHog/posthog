import structlog
from temporalio import activity

from posthog.temporal.ai.slack_app.types import PostHogSlackFirstPatrolInputs

logger = structlog.get_logger(__name__)


@activity.defn
def collect_first_patrol_digest_activity(inputs: PostHogSlackFirstPatrolInputs) -> dict | None:
    from products.slack_app.backend.first_patrol import (
        collect_first_patrol_digest,  # noqa: PLC0415 — Django app import deferred to activity runtime
    )

    return collect_first_patrol_digest(
        team_id=inputs.team_id,
        channel_name=inputs.channel_name,
        scout_config_ids=inputs.scout_config_ids,
        provisioned_at_iso=inputs.provisioned_at_iso,
    )


@activity.defn
def post_first_patrol_digest_activity(inputs: PostHogSlackFirstPatrolInputs, digest: dict) -> None:
    from products.slack_app.backend.first_patrol import (
        post_first_patrol_digest,  # noqa: PLC0415 — Django app import deferred to activity runtime
    )

    post_first_patrol_digest(
        integration_id=inputs.integration_id,
        slack_user_id=inputs.slack_user_id,
        dm_channel_id=inputs.dm_channel_id,
        thread_ts=inputs.thread_ts,
        digest=digest,
    )
