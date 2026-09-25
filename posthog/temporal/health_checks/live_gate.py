"""Per-team live/dry posture for a health check, read from a feature flag.

A check's `dry_run` is a class attribute. It is frozen at import into
`HealthCheckRegistration` and baked into the Temporal schedule by a deploy-time command.
So turning a check live takes a deploy, and turning it live for one team but not the rest
cannot be expressed at all. `rollout_percentage` does not fill the gap, because
`filter_ids_for_rollout` is a hash sample over team ids. It gives "1% of teams, chosen for
you", never "team 2".

The flag key is a convention rather than a field on the registration, so every check gets
one without a registry change: `health-check-<kind>-live`, with the kind's underscores
written as hyphens.

Resolution, per team:

- the flag reads `True`      -> live, write this team's issues
- the flag reads `False`     -> dry, log them and write nothing
- the flag reads nothing     -> `default_dry_run` decides

"Reads nothing" covers a flag that does not exist, a cold local-evaluation cache, a read
that raised, and a condition that cannot be decided from what `_posture_flag_value` sends.
All four fall back to the posture the check already had. That is what keeps a kind with no
flag behaving exactly as it did before this module existed, and what stops an unreadable
flag from turning a dry check live.

The sharp edge is that `False` and "no rule matched" arrive as the same value. Local
evaluation returns `False` for a team that matches no release condition, and reports the
inconclusive result that reads here as nothing only when a condition cannot be evaluated
at all. So a flag at a partial rollout takes every unmatched team dry. On a check whose
`dry_run` is False that stops its writes, and those teams keep their active issues with no
`resolved` event, because the resolve is scoped to the live teams too. Create such a flag
at 100% and express the exclusions as conditions. A multivariate flag would separate the
two cases, at the cost of the percentage rollout control.
"""

from posthog.ph_client import get_feature_flag_or_none


def live_flag_key(kind: str) -> str:
    return f"health-check-{kind.replace('_', '-')}-live"


def _posture_flag_value(flag_key: str, team_id: int) -> bool | None:
    """Read one team's posture flag, or None when the flag does not decide.

    Evaluation is local-only. A batch is hundreds of teams, so a remote read would be
    hundreds of HTTP calls on a path that must not block. `posthog/apps.py` wires the
    flag-definition cache and loads definitions at boot, so a cold cache reads None and the
    check's own posture stands rather than the process waiting on a per-team request.

    Local evaluation can only decide conditions it computes from what is passed here, which
    is the team id under two shapes: `team_<id>` as the distinct id, so a percentage
    rollout works, and the `project` group, so one team is targetable by `project.id`. A
    condition on any other property is inconclusive and reads as None.
    """
    project_id = str(team_id)
    value = get_feature_flag_or_none(
        flag_key,
        f"team_{team_id}",
        groups={"project": project_id},
        group_properties={"project": {"id": project_id}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )
    # A variant string means someone made the flag multivariate, which is not a posture.
    return value if isinstance(value, bool) else None


def live_team_ids(kind: str, team_ids: list[int], *, default_dry_run: bool) -> set[int]:
    """Return the teams this run may write issues for. Every other team stays dry."""
    flag_key = live_flag_key(kind)
    live: set[int] = set()

    for team_id in team_ids:
        flag_value = _posture_flag_value(flag_key, team_id)
        is_live = (not default_dry_run) if flag_value is None else flag_value
        if is_live:
            live.add(team_id)

    return live
