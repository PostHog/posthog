from posthog.models.team import Team
from posthog.warehouse.models import DataWarehouseViewLink
from typing import Dict


def get_view_link_columns(team: Team) -> Dict:
    from posthog.warehouse.api.saved_query import DataWarehouseSavedQuerySerializer

    columns = {}
    view_links = DataWarehouseViewLink.objects.filter(team=team)
    for view_link in view_links:
        columns.update({view_link.table: DataWarehouseSavedQuerySerializer(view_link.saved_query).data["columns"]})

    return columns
