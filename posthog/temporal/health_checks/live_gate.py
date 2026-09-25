"""Choose each team's health-check write posture at run time."""

from posthog.ph_client import get_feature_flag_or_none


def live_flag_key(kind: str) -> str:
    return f"health-check-{kind.replace('_', '-')}-live"


def _posture_flag_value(kind: str, team_id: int) -> bool | None:
    """Use local evaluation to avoid a remote request for every team in a batch."""
    value = get_feature_flag_or_none(
        live_flag_key(kind),
        f"team_{team_id}",
        groups={"project": str(team_id)},
        group_properties={"project": {"id": str(team_id)}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )
    return value if isinstance(value, bool) else None


def partition_teams_by_posture(
    kind: str,
    team_ids: list[int],
    *,
    default_dry_run: bool,
) -> tuple[list[int], list[int]]:
    live: list[int] = []
    dry: list[int] = []

    for team_id in team_ids:
        flag_value = _posture_flag_value(kind, team_id)
        is_live = (not default_dry_run) if flag_value is None else flag_value
        (live if is_live else dry).append(team_id)

    return live, dry
