"""Whether a user may still see an alert, by the access rules of the source product that owns it.

The platform imports no source, so each source registers its check when Django starts. A source
with no check registered lets nobody see its alerts this way.
"""

from uuid import UUID

from products.alerts_platform.backend.facade.contracts import SourceAlertViewer, SourceKind

_viewers: dict[SourceKind, SourceAlertViewer] = {}


def register(source: SourceKind, viewer: SourceAlertViewer) -> None:
    registered = _viewers.get(source)
    if registered is not None and registered is not viewer:
        raise RuntimeError(f"A different viewer check is already registered for {source} alerts.")
    _viewers[source] = viewer


def can_view(source: SourceKind, *, team_id: int, alert_id: UUID, user_id: int) -> bool:
    viewer = _viewers.get(source)
    return viewer is not None and viewer(team_id=team_id, alert_id=alert_id, user_id=user_id)
