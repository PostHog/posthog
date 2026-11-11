from products.dashboards.backend.facade.contracts import DashboardTemplateDefinition
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_templates import DashboardTemplate

STARTER_DASHBOARD_NAME = "Your starter dashboard"


def create_global_template_if_missing(template: DashboardTemplateDefinition) -> bool:
    if DashboardTemplate.objects.filter(template_name=template.template_name, team__isnull=True).exists():
        return False
    DashboardTemplate.objects.create(
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
    return True


def create_starter_dashboard(*, team_id: int) -> Dashboard:
    # Imported at call time: the helper module imports the subscriptions facade, which loads the
    # exports facade, and the exports facade imports the dashboards facade.
    from posthog.helpers.dashboard_templates import create_from_template  # noqa: PLC0415

    template = DashboardTemplate.default_signup_template()
    dashboard = Dashboard.objects.create(
        name=STARTER_DASHBOARD_NAME,
        pinned=True,
        team_id=team_id,
        description=template.dashboard_description or "",
    )
    create_from_template(dashboard, template)
    return dashboard
