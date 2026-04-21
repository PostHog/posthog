"""Typed CDC config parsed from ``ExternalDataSource.job_inputs``.

CDC fields (slot name, publication name, management mode, lag thresholds, …) live
in ``source.job_inputs`` (a JSON field) but are NOT part of the user-facing form,
so they don't appear in the auto-generated ``PostgresSourceConfig``. This module
provides a typed wrapper so consumers don't have to do dict access.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from posthog.temporal.data_imports.cdc.adapters import CDCConfig, ManagementMode

if TYPE_CHECKING:
    from products.data_warehouse.backend.models import ExternalDataSource

DEFAULT_LAG_WARNING_THRESHOLD_MB = 1024
DEFAULT_LAG_CRITICAL_THRESHOLD_MB = 10240


@dataclasses.dataclass(frozen=True, kw_only=True)
class PostgresCDCConfig(CDCConfig):
    """Typed view of the CDC-related fields stored in ``source.job_inputs``.

    Inherits the universal CDC fields (slot/publication/management/lag) from
    ``CDCConfig`` and adds postgres-specific extras such as ``consistent_point``.
    """

    consistent_point: str | None

    @classmethod
    def from_dict(cls, job_inputs: dict | None) -> PostgresCDCConfig:
        ji = job_inputs or {}
        management_mode: ManagementMode = (
            "self_managed" if ji.get("cdc_management_mode") == "self_managed" else "posthog"
        )
        return cls(
            enabled=bool(ji.get("cdc_enabled", False)),
            slot_name=ji.get("cdc_slot_name") or "",
            publication_name=ji.get("cdc_publication_name") or "",
            management_mode=management_mode,
            lag_warning_threshold_mb=int(ji.get("cdc_lag_warning_threshold_mb", DEFAULT_LAG_WARNING_THRESHOLD_MB)),
            lag_critical_threshold_mb=int(ji.get("cdc_lag_critical_threshold_mb", DEFAULT_LAG_CRITICAL_THRESHOLD_MB)),
            auto_drop_slot=bool(ji.get("cdc_auto_drop_slot", True)),
            consistent_point=ji.get("cdc_consistent_point"),
        )

    @classmethod
    def from_source(cls, source: ExternalDataSource) -> PostgresCDCConfig:
        return cls.from_dict(source.job_inputs)
