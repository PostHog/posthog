"""Show what a guest invite's grants let the guest view, including the items those grants embed."""

from collections.abc import Sequence

from posthog.dataclasses import frozen
from posthog.models.organization_invite import GuestGrantResource

from products.dashboards.backend.facade.api import dashboard_refs, insight_ids_on_dashboard
from products.dashboards.backend.facade.authorization import active_authorization_dashboard_ids
from products.notebooks.backend.facade.authorization import notebook_embeds
from products.product_analytics.backend.facade.models import Insight


@frozen
class GuestGrantInclude:
    resource: str
    id: str
    name: str | None


@frozen
class GuestGrantPreview:
    resource: str
    id: str | None
    name: str | None
    includes: tuple[GuestGrantInclude, ...]


@frozen
class GuestGrant:
    resource: str
    id: str | None


def _insight_includes(
    team_id: int, *, ids: Sequence[int] = (), short_ids: Sequence[str] = ()
) -> list[GuestGrantInclude]:
    insights = Insight.objects.filter(team_id=team_id, deleted=False)
    insights = insights.filter(id__in=ids) if ids else insights.filter(short_id__in=short_ids)
    return [
        GuestGrantInclude(resource=GuestGrantResource.INSIGHT, id=str(id), name=name or derived_name)
        for id, name, derived_name in insights.order_by("id").values_list("id", "name", "derived_name")
    ]


def guest_grants_preview(team_id: int, grants: Sequence[GuestGrant]) -> list[GuestGrantPreview]:
    """Return one preview per grant, in grant order. Grants that name no live object in the project are left out."""
    dashboard_ids = {grant.id for grant in grants if grant.resource == GuestGrantResource.DASHBOARD and grant.id}
    live_dashboard_ids = active_authorization_dashboard_ids(team_id, dashboard_ids)
    dashboard_names = {
        str(ref.id): ref.name for ref in dashboard_refs([int(id) for id in live_dashboard_ids if id.isdecimal()])
    }
    notebook_ids = {grant.id for grant in grants if grant.resource == GuestGrantResource.NOTEBOOK and grant.id}
    notebooks = {str(notebook.id): notebook for notebook in notebook_embeds(team_id, notebook_ids)}
    insight_ids = [
        int(grant.id)
        for grant in grants
        if grant.resource == GuestGrantResource.INSIGHT and grant.id and grant.id.isdecimal()
    ]
    insights = {include.id: include for include in _insight_includes(team_id, ids=insight_ids)} if insight_ids else {}

    previews: list[GuestGrantPreview] = []
    for grant in grants:
        if grant.id is None:
            previews.append(GuestGrantPreview(resource=grant.resource, id=None, name=None, includes=()))
        elif grant.resource == GuestGrantResource.DASHBOARD and grant.id in dashboard_names:
            on_dashboard = list(insight_ids_on_dashboard(int(grant.id)))
            previews.append(
                GuestGrantPreview(
                    resource=grant.resource,
                    id=grant.id,
                    name=dashboard_names[grant.id],
                    includes=tuple(_insight_includes(team_id, ids=on_dashboard)) if on_dashboard else (),
                )
            )
        elif grant.resource == GuestGrantResource.NOTEBOOK and grant.id in notebooks:
            notebook = notebooks[grant.id]
            embedded = (
                _insight_includes(team_id, short_ids=sorted(notebook.insight_short_ids))
                if notebook.insight_short_ids
                else []
            )
            recordings = [
                GuestGrantInclude(resource="session_recording", id=session_id, name=None)
                for session_id in sorted(notebook.recording_ids)
            ]
            previews.append(
                GuestGrantPreview(
                    resource=grant.resource, id=grant.id, name=notebook.title, includes=(*embedded, *recordings)
                )
            )
        elif grant.resource == GuestGrantResource.INSIGHT and grant.id in insights:
            previews.append(
                GuestGrantPreview(resource=grant.resource, id=grant.id, name=insights[grant.id].name, includes=())
            )
    return previews
