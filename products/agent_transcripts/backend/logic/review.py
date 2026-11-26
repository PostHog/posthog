"""The organization and the person behind each submission, for the staff review."""

from collections.abc import Collection
from uuid import UUID

from posthog.models.organization import Organization
from posthog.models.user import User

from ..facade.contracts import Submitter


def organization_names(organization_ids: Collection[UUID]) -> dict[UUID, str]:
    return dict(Organization.objects.filter(id__in=organization_ids).values_list("id", "name"))


def submitters(user_ids: Collection[int]) -> dict[int, Submitter]:
    users = User.objects.filter(id__in=user_ids).only("id", "first_name", "last_name", "email")
    return {
        user.id: Submitter(user_id=user.id, name=f"{user.first_name} {user.last_name}".strip(), email=user.email)
        for user in users
    }
