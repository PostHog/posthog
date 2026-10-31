from posthog.dataclasses import frozen
from posthog.ingress.dispatch.database import bounded_statement_timeout
from posthog.models.integration import Integration
from posthog.models.team.team import Team


def installation_id(payload: dict) -> str | None:
    """The delivery's GitHub App installation id, in the form the integration rows store it."""
    raw_installation_id = (payload.get("installation") or {}).get("id")
    return None if raw_installation_id is None else str(raw_installation_id)


# The run lookup these feed reads TaskRun off the writer, and they run on the request path
# outside the bounded attribution block. Pin them to the writer too: a replica-opted
# Integration or Team would otherwise let a slow replica stall a delivery whose own lookup
# never needed it, and replica lag could hide a freshly connected installation.
SCOPE_DB_ALIAS = "default"

# Every GitHub consumer on a delivery shares one wall-clock budget, and that budget cannot
# interrupt a query already in flight, so the installation lookup carries its own cap.
_INSTALLATION_LOOKUP_TIMEOUT_MS = 800


@frozen
class InstallationIntegration:
    """One project's connection to a GitHub App installation."""

    id: int
    team_id: int


def installation_integrations(external_id: str) -> tuple[InstallationIntegration, ...]:
    """The team integrations connected to a GitHub App installation, ordered by team.

    Raises the database error when the capped lookup fails, so each caller applies its own failure policy.
    """
    with bounded_statement_timeout(_INSTALLATION_LOOKUP_TIMEOUT_MS, aliases=[SCOPE_DB_ALIAS]):
        rows = (
            Integration.objects.using(SCOPE_DB_ALIAS)
            .filter(kind="github", integration_id=external_id)
            .order_by("team_id", "id")
            .values_list("id", "team_id")
        )
        return tuple(InstallationIntegration(id=row_id, team_id=team_id) for row_id, team_id in rows)


def installation_team_ids(payload: dict) -> list[int]:
    """Teams whose GitHub Integration matches the delivery's installation, in deterministic order.

    Empty when the payload carries no installation id or no Integration matches it.
    """
    external_id = installation_id(payload)
    if external_id is None:
        return []

    # One installation can link to several teams. The order only keeps results stable, so never treat
    # the first team as the owner. See posthog/ingress/github/README.md#picking-the-project.
    return [integration.team_id for integration in installation_integrations(external_id)]


def _resolve_external_team(payload: dict) -> Team | None:
    team_ids = installation_team_ids(payload)
    if not team_ids:
        return None
    return Team.objects.filter(pk=team_ids[0]).first()
