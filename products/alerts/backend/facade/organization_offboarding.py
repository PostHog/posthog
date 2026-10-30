from posthog.organization_offboarding_types import OffboardingResource

from products.alerts.backend.logic.organization_offboarding import AlertOffboarding


def list_member_offboarding_resources(organization_id: str, user_id: int) -> list[OffboardingResource]:
    return AlertOffboarding(organization_id, user_id).resources()


def update_member_offboarding_resource(organization_id: str, user_id: int, resource_id: str, enabled: bool) -> None:
    AlertOffboarding(organization_id, user_id).update(resource_id, enabled)
