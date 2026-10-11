from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

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


_InstallationLookup = tuple[InstallationIntegration, ...] | Exception

# None outside a lookup scope, so a Celery task or a shell always reads fresh rows.
_lookups: ContextVar[dict[str, _InstallationLookup] | None] = ContextVar("github_installation_lookups", default=None)


@contextmanager
def installation_lookup_scope() -> Iterator[None]:
    """Share installation lookups between everything that runs inside the block.

    Every consumer on a GitHub delivery needs the same installation-to-team mapping, so the
    ingress view opens one scope per request and the first consumer that asks pays for the query.
    """
    token = _lookups.set({})
    try:
        yield
    finally:
        _lookups.reset(token)


def installation_integrations(external_id: str) -> tuple[InstallationIntegration, ...]:
    """The team integrations connected to a GitHub App installation, ordered by team.

    Raises the database error when the capped lookup fails. Inside a lookup scope the failure is
    remembered too, so every caller gets the same answer and applies its own failure policy
    without each of them waiting out the cap again.
    """
    lookups = _lookups.get()
    if lookups is not None and external_id in lookups:
        cached = lookups[external_id]
        if isinstance(cached, Exception):
            raise cached
        return cached

    try:
        with bounded_statement_timeout(_INSTALLATION_LOOKUP_TIMEOUT_MS, aliases=[SCOPE_DB_ALIAS]):
            rows = (
                Integration.objects.using(SCOPE_DB_ALIAS)
                .filter(kind="github", integration_id=external_id)
                .order_by("team_id", "id")
                .values_list("id", "team_id")
            )
            result = tuple(InstallationIntegration(id=row_id, team_id=team_id) for row_id, team_id in rows)
    except Exception as error:
        if lookups is not None:
            lookups[external_id] = error
        raise

    if lookups is not None:
        lookups[external_id] = result
    return result


def installation_team_ids(payload: dict) -> list[int]:
    """Teams whose GitHub Integration matches the delivery's installation, in deterministic order.

    Empty when the payload carries no installation id or no Integration matches it — the
    lookups that take this fall back to their unscoped behaviour in that case.
    """
    external_id = installation_id(payload)
    if external_id is None:
        return []

    # One installation can map to multiple teams; the ordering makes attribution deterministic.
    return [integration.team_id for integration in installation_integrations(external_id)]


def _resolve_external_team(payload: dict) -> Team | None:
    team_ids = installation_team_ids(payload)
    if not team_ids:
        return None
    return Team.objects.filter(pk=team_ids[0]).first()
