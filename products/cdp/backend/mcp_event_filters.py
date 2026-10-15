from rest_framework.exceptions import PermissionDenied

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import Table
from posthog.hogql.database.schema.events import EventsGroupSubTable, EventsPersonSubTable, EventsTable
from posthog.hogql.restricted_properties import restricted_property_keys_for_table_type

from posthog.models import Team, User

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.cdp.backend.filters import FilterPropertyReferences
from products.cdp.backend.mcp_event_properties import MCPEventPropertyAccess


class MCPEventFilterAccessValidator:
    @classmethod
    def validate(cls, expression: ast.Expr, *, team: Team, user: User) -> None:
        references = FilterPropertyReferences()
        references.visit(expression)
        cls.validate_snapshot(references.references, team=team, user=user)

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
            for name in names:
                MCPEventPropertyAccess.validate(name, keys)
