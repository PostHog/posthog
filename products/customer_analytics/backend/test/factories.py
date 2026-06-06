from typing import Any

from products.customer_analytics.backend.models import Account


def create_account(*, team_id: int, name: str = "Acme Corp", **kwargs: Any) -> Account:
    """Create an Account for tests. Always supplies `team_id` to make team-isolation cases ergonomic."""
    return Account.objects.unscoped().create(team_id=team_id, name=name, **kwargs)
