from posthog.api.test.test_organization import create_organization as create_organization_base
from posthog.constants import AvailableFeature
from posthog.models import Organization


def create_organization(name: str, has_data_pipelines_feature: bool = True) -> Organization:
    organization = create_organization_base(name)
    if has_data_pipelines_feature:
        organization.available_product_features = [
            {"key": AvailableFeature.DATA_PIPELINES, "name": AvailableFeature.DATA_PIPELINES}
        ]
        organization.save()
    return organization
