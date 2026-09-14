from products.customer_analytics.backend.models import CustomPropertySource, TargetType
from products.warehouse_sources.backend.facade.hooks import (
    BINDING_KIND_SAVED_QUERY,
    AccountPropertySourceProjection,
    WarehouseBinding,
)


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
    if not sources:
        return None
    return [
        AccountPropertySourceProjection(
            key_column=source.key_column,
            columns=frozenset({source.key_column, source.source_column}),
        )
        for source in sources
        if source.source_column
    ]
