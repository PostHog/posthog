from typing import Optional

from django.db.models import Q

import posthoganalytics

from posthog.hogql.team_context import HogQLTeamContext

from posthog.models import Team

from products.data_tools.backend.models.join import DataWarehouseJoin
from products.warehouse_sources.backend.models.util import get_view_or_table_by_name


class DjangoDataProvider:
    """The ORM-backed ``DataProvider`` — the Django side of the engine's data port.

    Holds the requesting team (fetched lazily when only an id is known) and answers the
    engine's mid-compile data questions by querying the database. Reads happen at the
    moment the engine asks, exactly as they did when engine code queried the ORM
    directly — only the routing changed.
    """

    def __init__(self, team: Optional[Team] = None, team_id: Optional[int] = None):
        self._team = team
        self._team_id = team_id if team_id is not None else (team.id if team is not None else None)
        self._team_context: Optional[HogQLTeamContext] = None

    @property
    def team(self) -> Team:
        if self._team is None:
            if self._team_id is None:
                raise ValueError("DjangoDataProvider needs a team or team_id to answer data queries")
            self._team = Team.objects.get(id=self._team_id)
        return self._team

    @property
    def team_context(self) -> HogQLTeamContext:
        if self._team_context is None:
            self._team_context = HogQLTeamContext.from_team(self.team)
        return self._team_context

    def person_warehouse_property_type(self, field_name: str | int, property_key: str) -> Optional[str]:
        # TODO: pass id of table item being filtered on instead of searching through joins
        current_join: DataWarehouseJoin | None = (
            DataWarehouseJoin.objects.filter(Q(deleted__isnull=True) | Q(deleted=False))
            .filter(team=self.team, source_table_name="persons", field_name=field_name)
            .first()
        )

        if not current_join:
            raise Exception(f"Could not find join for key {field_name}")

        table_or_view = get_view_or_table_by_name(self.team, current_join.joining_table_name)
        if not table_or_view:
            raise Exception(f"Could not find table or view for key {field_name}")

        if table_or_view.columns is not None:
            prop_type_dict = table_or_view.columns.get(property_key, None)
            if prop_type_dict is not None:
                return prop_type_dict.get("hogql")

        return None

    def persons_join_uses_inner_join(self) -> bool:
        organization = self.team.organization
        # TODO: @raquelmsmith: Remove flag check and use left join for all once deletes are caught up
        return bool(
            posthoganalytics.feature_enabled(
                "personless-events-not-supported",
                str(self.team.uuid),
                groups={"organization": str(organization.id)},
                group_properties={
                    "organization": {
                        "id": str(organization.id),
                        "created_at": organization.created_at,
                    }
                },
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
