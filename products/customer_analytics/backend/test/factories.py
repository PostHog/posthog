from typing import Any

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
