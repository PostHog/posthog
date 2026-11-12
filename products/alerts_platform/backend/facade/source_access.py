"""Facade for whether a user may still see an alert, by the source product's own access rules."""

from products.alerts_platform.backend.facade.contracts import SourceAlertViewer, SourceKind
from products.alerts_platform.backend.logic import source_access


def register_source_alert_viewer(source: SourceKind, viewer: SourceAlertViewer) -> None:
    source_access.register(source, viewer)
