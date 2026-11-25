"""Who may create a project in an organization, and how many projects the organization may hold.

The projects API applies these rules through its DRF permission classes. Code that creates a
project outside that API, such as partner provisioning, calls these functions directly.
"""

from enum import StrEnum

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization, ProductFeature
from posthog.models.user import User

from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import Action

MAX_ALLOWED_PROJECTS_PER_ORG = 2000

# An organization without the organizations_projects feature gets this many non-demo projects.
PROJECT_LIMIT_WITHOUT_FEATURE = 1

PROJECT_CREATION_REQUIRES_ADMIN_MESSAGE = "You need to be an organization admin or above to create new projects."
PLAN_PROJECT_LIMIT_MESSAGE = (
    "You have reached the maximum limit of allowed projects for your current plan. "
    "Upgrade your plan to be able to create and manage more projects."
)
ORGANIZATION_PROJECT_LIMIT_MESSAGE = (
    f"You have reached the maximum limit of {MAX_ALLOWED_PROJECTS_PER_ORG} projects per organization. "
    "Contact support if you'd like access to more projects."
)


class ProjectLimit(StrEnum):
    PLAN = "plan"
    ORGANIZATION_MAXIMUM = "organization_maximum"


PROJECT_LIMIT_MESSAGES: dict[ProjectLimit, str] = {
    ProjectLimit.PLAN: PLAN_PROJECT_LIMIT_MESSAGE,
    ProjectLimit.ORGANIZATION_MAXIMUM: ORGANIZATION_PROJECT_LIMIT_MESSAGE,
}


def reached_project_limit(non_demo_project_count: int, projects_feature: ProductFeature | None) -> ProjectLimit | None:
    """The limit that refuses one more non-demo project, or None when the organization can add one."""
    if not projects_feature:
        if non_demo_project_count >= PROJECT_LIMIT_WITHOUT_FEATURE:
            return ProjectLimit.PLAN
        return None

    allowed_project_count = projects_feature.get("limit")
    if allowed_project_count is not None and non_demo_project_count >= allowed_project_count:
        return ProjectLimit.PLAN
    # Every plan stops at the per-organization maximum, including one whose limit is higher.
    if non_demo_project_count >= MAX_ALLOWED_PROJECTS_PER_ORG:
        return ProjectLimit.ORGANIZATION_MAXIMUM
    return None


def count_non_demo_projects(organization: Organization) -> int:
    return organization.teams.exclude(is_demo=True).distinct("project_id").count()


def organization_project_limit_reached(organization: Organization) -> ProjectLimit | None:
    return reached_project_limit(
        count_non_demo_projects(organization),
        organization.get_available_feature(AvailableFeature.ORGANIZATIONS_PROJECTS),
    )


def member_can_create_projects(user: User, organization: Organization) -> bool:
    """Admins and owners can create projects. Members can only when the organization allows it and
    has the entitlement to configure that. Without the entitlement, members can never create one.

    The caller checks that the user is a member of the organization."""
    if authorization.check(
        resource=Resource.organization(organization.id), action=Action.EDIT, subject=Subject(user_id=user.pk)
    ):
        return True

    # Gated behind the org invite-settings entitlement for now (will move to a dedicated feature later).
    if not organization.is_feature_available(AvailableFeature.ORGANIZATION_INVITE_SETTINGS):
        return False

    return bool(organization.members_can_create_projects)
