"""Who a source's own settings say to email, beside the destinations a person added.

A warehouse alert can email the project members who get data pipeline error emails, for example.
The platform imports no source, so a source registers its lookup here when Django starts.
"""

from uuid import UUID

from products.alerts_platform.backend.facade.contracts import SourceKind, SourceRecipients

_recipients: dict[SourceKind, SourceRecipients] = {}


def register(source: SourceKind, recipients: SourceRecipients) -> None:
    # One owner per source. A second registrant would silently replace who the first one emails.
    registered = _recipients.get(source)
    if registered is not None and registered is not recipients:
        raise RuntimeError(f"A different recipient lookup is already registered for {source} alerts.")
    _recipients[source] = recipients


def addresses(source: SourceKind, *, team_id: int, configuration_id: UUID) -> tuple[str, ...]:
    """The addresses to email about the alert, or none for a source that registered no lookup."""
    recipients = _recipients.get(source)
    if recipients is None:
        return ()
    # Sorted and deduplicated, because delivery tells destinations apart by their data. The same
    # people in another order would read as a second destination.
    return tuple(
        sorted({address for address in recipients(team_id=team_id, configuration_id=configuration_id) if address})
    )
