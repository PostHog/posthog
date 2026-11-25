from typing import TYPE_CHECKING

from django.db import router

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.facade.contracts import DashboardTemplateDefinition
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_templates import DashboardTemplate

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

STARTER_DASHBOARD_NAME = "Your starter dashboard"


def unsaved_template(template: DashboardTemplateDefinition) -> DashboardTemplate:
    return DashboardTemplate(
        team_id=None,
        template_name=template.template_name,
        dashboard_description=template.dashboard_description,
        dashboard_filters=template.dashboard_filters,
        tiles=template.tiles,
        variables=template.variables,
        tags=template.tags,
        image_url=template.image_url,
        scope=template.scope.value if template.scope is not None else None,
        availability_contexts=template.availability_contexts,
    )


def create_global_template_if_missing(template: DashboardTemplateDefinition) -> bool:
    if DashboardTemplate.objects.filter(template_name=template.template_name, team__isnull=True).exists():
        return False
    unsaved_template(template).save(force_insert=True)
    return True


def create_starter_dashboard(*, team_id: int) -> Dashboard:
    # Imported at call time: the helper module imports the subscriptions facade, which loads the
    # exports facade, and the exports facade imports the dashboards facade.
    from posthog.helpers.dashboard_templates import create_from_template  # noqa: PLC0415
    from posthog.models.team import Team  # noqa: PLC0415

    # The customization module loads the widget registry, which imports the dashboards facade.
    from products.dashboards.backend.customization import stored_customization  # noqa: PLC0415

    # Signup calls this in the transaction that inserts the team, which a read replica cannot see yet.
    # Reading the team from the writer once also spares the dashboard save and the template tiles a read.
    team = Team.objects.db_manager(router.db_for_write(Team)).get(pk=team_id)
    template = DashboardTemplate.default_signup_template()
    dashboard = Dashboard.objects.create(
        name=STARTER_DASHBOARD_NAME,
        pinned=True,
        team=team,
        description=template.dashboard_description or "",
        # With the template's values set here, the template step logs no second "updated" activity entry.
        filters=template.dashboard_filters,
        customization=stored_customization(template.customization),
    )
    create_from_template(dashboard, template)
    return dashboard


def create_unlisted_dashboard(*, team: "Team", user: "User", template: DashboardTemplateDefinition) -> Dashboard:
    # Imported at call time for the same import cycle as in create_starter_dashboard.
    from posthog.helpers.dashboard_templates import create_from_template  # noqa: PLC0415

    template_row = unsaved_template(template)
    dashboard = Dashboard.objects.create(
        team_id=team.id,
        name=template_row.template_name,
        description=template_row.dashboard_description or "",
        filters={**(template_row.dashboard_filters or {}), "__template_version": 1},
        created_by=user,
        creation_mode=Dashboard.CreationMode.UNLISTED,
    )
    create_from_template(dashboard, template_row, user, user_access_control=UserAccessControl(user=user, team=team))
    return dashboard
