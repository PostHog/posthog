from typing import Any

from posthog.models.user import User

from products.dashboards.backend.models.dashboard import Dashboard


def create_empty_dashboard(
    *, team_id: int, name: str, description: str, pinned: bool, variables: dict[str, Any]
) -> Dashboard:
    return Dashboard.objects.create(
        team_id=team_id, name=name, description=description, pinned=pinned, variables=variables
    )


def create_template_dashboard(
    *, team_id: int, name: str, description: str, filters: dict[str, Any], created_by: User
) -> Dashboard:
    """A dashboard row that a template step fills with tiles next."""
    return Dashboard.objects.create(
        team_id=team_id,
        name=name,
        description=description,
        filters=filters,
        created_by=created_by,
        creation_mode=Dashboard.CreationMode.TEMPLATE,
    )
