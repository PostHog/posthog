"""Facade for the report of differences between platform-owned alerts' source rows and their copies."""

from products.alerts_platform.backend.facade.contracts import LegacyDriftSource, SourceKind
from products.alerts_platform.backend.logic import legacy_config_drift


def register_legacy_drift_source(source: SourceKind, provider: LegacyDriftSource) -> None:
    """Lets the drift report read a source's platform-owned rows, which the platform cannot import."""
    legacy_config_drift.register(source, provider)
