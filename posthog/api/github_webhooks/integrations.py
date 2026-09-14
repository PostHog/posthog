from posthog.models.integration import Integration
from posthog.models.team.team import Team


def _installation_id(payload: dict) -> str | None:
    """The delivery's GitHub App installation id, in the form the integration rows store it."""
    installation_id = (payload.get("installation") or {}).get("id")
    return None if installation_id is None else str(installation_id)


# The run lookup these feed reads TaskRun off the writer, and they run on the request path
# outside the bounded attribution block. Pin them to the writer too: a replica-opted
# Integration or Team would otherwise let a slow replica stall a delivery whose own lookup
# never needed it, and replica lag could hide a freshly connected installation.
_SCOPE_DB_ALIAS = "default"


def _installation_team_ids(payload: dict) -> list[int]:
    """Teams whose GitHub Integration matches the delivery's installation, in deterministic order.

    Empty when the payload carries no installation id or no Integration matches it — the
    lookups that take this fall back to their unscoped behaviour in that case.
    """
    external_id = _installation_id(payload)
    if external_id is None:
        return []

    # One installation can map to multiple teams; order_by makes attribution deterministic.
    return list(
        Integration.objects.using(_SCOPE_DB_ALIAS)
        .filter(kind="github", integration_id=external_id)
        .order_by("team_id")
        .values_list("team_id", flat=True)
    )


def _resolve_external_team(payload: dict) -> Team | None:
    team_ids = _installation_team_ids(payload)
    if not team_ids:
        return None
    return Team.objects.filter(pk=team_ids[0]).first()
