import dagster


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
    },
)
def get_all_team_ids_op(context: dagster.OpExecutionContext):
    """Fetch all team IDs to process in batches."""
    from posthog.models.team import Team

    override_team_ids = context.op_config["team_ids"]
    batch_size = context.op_config.get("batch_size", 1000)

    if override_team_ids:
        team_ids = override_team_ids
        context.log.info(f"Processing {len(team_ids)} configured teams: {team_ids}")
    else:
        team_ids = list(Team.objects.exclude(id=0).values_list("id", flat=True))
        context.log.info(f"Processing all {len(team_ids)} teams")

    for i in range(0, len(team_ids), batch_size):
        batch = team_ids[i : i + batch_size]
        yield dagster.DynamicOutput(batch, mapping_key=f"batch_{i // batch_size}")
