from typing import Any

from django.apps import apps

from products.customer_analytics.backend.models import Account, CustomPropertyDefinition, DisplayType


def create_account(*, team_id: int, name: str = "Acme Corp", **kwargs: Any) -> Account:
    """Create an Account for tests. Always supplies `team_id` to make team-isolation cases ergonomic."""
    return Account.objects.unscoped().create(team_id=team_id, name=name, **kwargs)


def create_custom_property_definition(
    *, team_id: int, name: str = "Plan", display_type: str = DisplayType.TEXT, **kwargs: Any
) -> CustomPropertyDefinition:
    """Create a CustomPropertyDefinition for tests, always supplying `team_id`."""
    return CustomPropertyDefinition.objects.unscoped().create(
        team_id=team_id, name=name, display_type=display_type, **kwargs
    )


def create_saved_query(
    *, team_id: int, name: str = "enriched_users", is_materialized: bool = True, **kwargs: Any
) -> Any:
    """Create a data-warehouse view for tests. Materialized by default, which is what a view-backed
    property source binds to.

    Resolved with ``apps.get_model`` because customer_analytics does not depend on data_modeling; the
    production code reaches the same model the same way.
    """
    saved_query_model = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
    return saved_query_model.objects.create(
        team_id=team_id, name=name, query={"query": "select 1"}, is_materialized=is_materialized, **kwargs
    )
