"""Choose each team's health-check write posture at run time."""

from posthog.ph_client import get_feature_flag_or_none


def live_flag_key(kind: str) -> str:
    return f"health-check-{kind.replace('_', '-')}-live"


def _posture_flag_value(flag_key: str, team_id: int) -> bool | None:
    """Use local evaluation to avoid a remote request for every team in a batch."""
    project_id = str(team_id)
    value = get_feature_flag_or_none(
        flag_key,
        f"team_{team_id}",
        groups={"project": project_id},
        group_properties={"project": {"id": project_id}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )
    return value if isinstance(value, bool) else None


def live_team_ids(kind: str, team_ids: list[int], *, default_dry_run: bool) -> set[int]:
    """Return the teams this run may write issues for. Every other team stays dry.

    The flag decides a team only when it reads as a boolean. A flag that does not exist,
    a cold local-evaluation cache, a read that raised, and a condition that cannot be
    evaluated from what `_posture_flag_value` sends all read as None, and `default_dry_run`
    decides those teams instead.
    """
    flag_key = live_flag_key(kind)
    live: set[int] = set()

    for team_id in team_ids:
        flag_value = _posture_flag_value(flag_key, team_id)
        is_live = (not default_dry_run) if flag_value is None else flag_value
        if is_live:
            live.add(team_id)

    return live
