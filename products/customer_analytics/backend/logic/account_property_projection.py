import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.customer_analytics.backend.constants import WAREHOUSE_ACCOUNT_PROPERTIES_S3_SYNC_FLAG
from products.customer_analytics.backend.models import CustomPropertySource, TargetType
from products.warehouse_sources.backend.facade.hooks import (
    BINDING_KIND_SAVED_QUERY,
    AccountPropertySourceProjection,
    WarehouseBinding,
)


def account_property_staging_enabled(team_id: int) -> bool:
    try:
        organization_id = str(Team.objects.only("organization_id").get(id=team_id).organization_id)
    except Team.DoesNotExist:
        return False
    try:
        return bool(
            posthoganalytics.feature_enabled(
                WAREHOUSE_ACCOUNT_PROPERTIES_S3_SYNC_FLAG,
                organization_id,
                groups={"organization": organization_id},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as error:
        capture_exception(error)
        return False


def account_property_projection(
    team_id: int, binding: WarehouseBinding
) -> list[AccountPropertySourceProjection] | None:
    if binding.kind != BINDING_KIND_SAVED_QUERY:
        return None
    sources = list(
        CustomPropertySource.objects.for_team(team_id)
        .select_related("definition")
        .filter(
            saved_query_id=binding.id,
            is_enabled=True,
            definition__target_type=TargetType.ACCOUNT.value,
            source_column__isnull=False,
        )
    )
    if not sources or not account_property_staging_enabled(team_id):
        return None
    return [
        AccountPropertySourceProjection(
            key_column=source.key_column,
            columns=frozenset({source.key_column, source.source_column}),
        )
        for source in sources
        if source.source_column
    ]
