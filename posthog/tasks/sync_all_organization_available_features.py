from typing import Sequence, cast

from posthog.models.organization import Organization


def sync_all_organization_available_features() -> None:
    for organization in cast(Sequence[Organization], Organization.objects.all().only("id")):
        organization.update_available_features()
        organization.save()
