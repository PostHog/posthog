from pydantic import JsonValue
from rest_framework.exceptions import PermissionDenied

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import Table
from posthog.hogql.database.schema.events import EventsGroupSubTable, EventsPersonSubTable, EventsTable
from posthog.hogql.restricted_properties import restricted_property_keys_for_table_type

from posthog.models import Team, User

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.cdp.backend.mcp_event_properties import MCPEventPropertyAccess
from products.cdp.backend.validation import action_ids_in_filters, require_viewer_access_to_actions


class MCPEventFilterAccessValidator:
    @staticmethod
    def validate_actions(filters: dict[str, JsonValue], *, team: Team, user: User) -> None:
        require_viewer_access_to_actions(
            UserAccessControl(user, team), team=team, action_ids=action_ids_in_filters(filters)
        )

    @staticmethod
    def validate_snapshot(dependencies: dict[str, list[str | None]], *, team: Team, user: User) -> None:
        restrictions = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.pk)
        if not restrictions:
            return
        context = HogQLContext(team_id=team.pk, restricted_properties=restrictions)
        table: Table
        for scope, names in dependencies.items():
            if scope == "event":
                table = EventsTable()
            elif scope == "person":
                table = EventsPersonSubTable()
            elif scope in {f"group:{index}" for index in range(5)}:
                table = EventsGroupSubTable(int(scope.removeprefix("group:")))
            else:
                raise PermissionDenied("The queued filter cannot be authorized.")
            keys = restricted_property_keys_for_table_type(ast.TableType(table=table), context)
            if scope == "event":
                keys = MCPEventPropertyAccess.with_group_aliases(keys, team=team)
            for name in names:
                MCPEventPropertyAccess.validate(name, keys)
