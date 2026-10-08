from typing import TYPE_CHECKING

from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.types import DIRECT_ENGINE_BY_SOURCE_TYPE, ExternalDataSourceAccessMethod

if TYPE_CHECKING:
    from posthog.models.team import Team

# Gates BigQuery direct query while it is tested internally. It exists for warehouse-native
# experiment metrics; teams outside the rollout must not be able to connect or query it.
BIGQUERY_DIRECT_QUERY_FLAG = "bigquery-direct-query"


def bigquery_direct_query_enabled(team: "Team") -> bool:
    # Function-local: keeps the analytics client off the django.setup() path.
    from posthog.ph_client import feature_enabled_or_false  # noqa: PLC0415

    return feature_enabled_or_false(
        BIGQUERY_DIRECT_QUERY_FLAG,
        str(team.uuid),
        groups={"organization": str(team.organization_id), "project": str(team.id)},
        group_properties={
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
        send_feature_flag_events=False,
    )


def direct_capable_source_types() -> frozenset[str]:
    """Source types that map to a direct-SQL engine (the static capability surface)."""
    return frozenset(DIRECT_ENGINE_BY_SOURCE_TYPE.keys())


def is_direct_capable(source: ExternalDataSource) -> bool:
    """Whether this source can be queried live via a direct connection.

    Pure-direct sources are always capable. Synced (warehouse) sources are capable only when
    the per-source toggle is on. Either way the source type must map to a known engine.
    """
    if source.direct_engine is None:
        return False
    if source.access_method == ExternalDataSourceAccessMethod.DIRECT:
        return True
    return source.direct_query_enabled


def direct_supports_hogql(source: ExternalDataSource) -> bool:
    """Whether HogQL compiles for this source's direct engine (False means raw SQL only)."""
    if source.direct_engine is None:
        return False
    # Function-local: the registry is populated by the package root, which pulls the drivers.
    from posthog.hogql.direct_sql.registry import get_adapter  # noqa: PLC0415

    adapter = get_adapter(source.direct_engine)
    return adapter is not None and adapter.dialect is not None
