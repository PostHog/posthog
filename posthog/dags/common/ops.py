import math
import hashlib

import dagster


def _team_rollout_rank(team_id: int) -> int:
    digest = hashlib.sha256(str(team_id).encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big")


def _filter_team_ids_for_rollout(team_ids: list[int], rollout_percentage: float) -> list[int]:
    if rollout_percentage < 0 or rollout_percentage > 100:
        raise ValueError(f"rollout_percentage must be in [0, 100], got {rollout_percentage}")
    if not team_ids:
        return []
    if rollout_percentage >= 100:
        return team_ids
    if rollout_percentage <= 0:
        return []

    target_count = max(1, math.ceil(len(team_ids) * rollout_percentage / 100))
    ranked_team_ids = sorted(team_ids, key=lambda team_id: (_team_rollout_rank(team_id), team_id))
    return ranked_team_ids[:target_count]


@dagster.op(
    out=dagster.DynamicOut(list[int]),
    config_schema={
        "team_ids": dagster.Field(
            dagster.Array(dagster.Int),
            default_value=[],
            is_required=False,
            description="Specific team IDs to process. If empty, processes all teams.",
        ),
        "batch_size": dagster.Field(
            dagster.Int,
            default_value=1000,
            is_required=False,
            description="Number of team IDs per batch.",
        ),
        "rollout_percentage": dagster.Field(
            dagster.Float,
            default_value=100.0,
            is_required=False,
            description="Percentage of teams to include deterministically (0-100, supports decimals).",
        ),
    },
)
def get_all_team_ids_op(context: dagster.OpExecutionContext):
    """Fetch all team IDs to process in batches."""
    from posthog.models.team import Team

    override_team_ids = context.op_config["team_ids"]
    batch_size = context.op_config.get("batch_size", 1000)
    rollout_percentage = float(context.op_config.get("rollout_percentage", 100.0))

    if rollout_percentage < 0 or rollout_percentage > 100:
        raise ValueError(f"rollout_percentage must be in [0, 100], got {rollout_percentage}")

    if override_team_ids:
        team_ids = override_team_ids
        context.log.info(f"Processing {len(team_ids)} configured teams: {team_ids}")
    else:
        team_ids = list(Team.objects.exclude(id=0).values_list("id", flat=True))
        context.log.info(f"Processing all {len(team_ids)} teams")

    if rollout_percentage < 100:
        team_ids = _filter_team_ids_for_rollout(team_ids, rollout_percentage)
        context.log.info(f"After rollout ({rollout_percentage}%), processing {len(team_ids)} teams")

    for i in range(0, len(team_ids), batch_size):
        batch = team_ids[i : i + batch_size]
        yield dagster.DynamicOutput(batch, mapping_key=f"batch_{i // batch_size}")
