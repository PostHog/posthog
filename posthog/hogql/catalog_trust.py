from collections.abc import Callable
from typing import TYPE_CHECKING, Optional

from posthog.schema import DataCatalogTrustWarning

from posthog.hogql import ast
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.resolver_utils import extract_base_table_types

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser

    from posthog.models.team import Team
    from posthog.models.user import User

# The advisory names tenant-authored strings; keep it compact so it stays a
# nudge, not a payload — and so a pathological table name can't bloat it.
_MAX_NAMED_TABLES = 3
_MAX_NAMED_METRICS = 5
_MAX_TABLE_NAME_CHARS = 100

_SelectType = "ast.SelectQueryType | ast.SelectSetQueryType | None"


def _sanitize_name(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch.isprintable() and ch not in "<>`")
    return cleaned[:_MAX_TABLE_NAME_CHARS]


def _used_warehouse_tables(
    select_type: "ast.SelectQueryType | ast.SelectSetQueryType | None",
) -> dict[str, str]:
    """Warehouse tables referenced by a *resolved* query, as ``table_id -> name``.

    Unlike ``extract_warehouse_sources`` this includes self-managed S3 tables —
    certification targets any ``DataWarehouseTable`` row, connector-synced or not.
    """
    if select_type is None:
        return {}
    used: dict[str, str] = {}
    for table_type in extract_base_table_types(select_type):
        table = table_type.table
        if not isinstance(table, S3Table):
            continue
        table_id = getattr(table, "table_id", None)
        if table_id:
            used.setdefault(str(table_id), getattr(table, "name", "") or "")
    return used


def build_data_catalog_trust_warning(
    team: "Team",
    user: "User | AnonymousUser | None",
    get_select_type: Callable[[], "ast.SelectQueryType | ast.SelectSetQueryType | None"],
) -> Optional[DataCatalogTrustWarning]:
    """Advisory for queries that read uncertified warehouse tables while the
    team's catalog holds approved governed metrics.

    The point-of-use trust signal: it fires on the exact path a satisficing
    reader walked, regardless of how they found the table. Fail-soft — the
    advisory must never break or slow down query execution — and restricted to
    authenticated users because it names catalog metadata (same posture as
    ``HogQLQueryExecutor._serialized_warehouse_sources``).
    """
    try:
        if user is None or not user.is_authenticated:
            return None

        # Deferred + facade-only imports: keep the product's (heavy) query-runner deps off this
        # module's import path, and respect the data_catalog isolation boundary.
        from products.data_catalog.backend.facade.api import certifications_for_team, metrics_for_team  # noqa: PLC0415
        from products.data_catalog.backend.facade.enums import CertificationStatus, MetricStatus  # noqa: PLC0415
        from products.data_catalog.backend.facade.flags import is_data_catalog_enabled  # noqa: PLC0415

        if not is_data_catalog_enabled(team):
            return None

        used_tables = _used_warehouse_tables(get_select_type())
        if not used_tables:
            return None

        certified_ids = {
            str(certification.table_id)
            for certification in certifications_for_team(team).filter(table_id__in=list(used_tables))
            if certification.status == CertificationStatus.CERTIFIED
        }
        uncertified = [_sanitize_name(name) for table_id, name in used_tables.items() if table_id not in certified_ids]
        if not uncertified:
            return None

        approved_metrics = list(
            metrics_for_team(team)
            .filter(status=MetricStatus.APPROVED)
            .values_list("name", flat=True)[:_MAX_NAMED_METRICS]
        )
        if not approved_metrics:
            return None

        named_tables = sorted(uncertified)[:_MAX_NAMED_TABLES]
        overflow = len(uncertified) - len(named_tables)
        table_list = ", ".join(named_tables) + (f" (and {overflow} more)" if overflow > 0 else "")
        metric_list = ", ".join(approved_metrics)
        return DataCatalogTrustWarning(
            uncertified_tables=named_tables,
            approved_metrics=approved_metrics,
            message=(
                f"This query read warehouse table(s) not certified in the data catalog: {table_list}. "
                f"Approved governed metrics exist ({metric_list}) — check system.information_schema.metrics "
                "before treating raw-table derivations as canonical."
            ),
        )
    except Exception:
        return None
