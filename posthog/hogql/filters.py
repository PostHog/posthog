from typing import List, Optional

from dateutil.parser import isoparse

from posthog.hogql import ast
from posthog.hogql.errors import HogQLException
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql.visitor import CloningVisitor
from posthog.models import Team
from posthog.schema import HogQLFilters
from posthog.utils import relative_date_parse


def replace_filters(node: ast.Expr, filters: Optional[HogQLFilters], team: Team) -> ast.Expr:
    return ReplaceFilters(filters, team).visit(node)


class ReplaceFilters(CloningVisitor):
    def __init__(self, filters: Optional[HogQLFilters], team: Team = None):
        super().__init__()
        self.filters = filters
        self.team = team
        self.selects: List[ast.SelectQuery] = []

    def visit_select_query(self, node):
        self.selects.append(node)
        node = super().visit_select_query(node)
        self.selects.pop()
        return node

    def visit_placeholder(self, node):
        if node.field == "filters":
            if self.filters is None:
                return ast.Constant(value=True)

            last_select = self.selects[-1]
            last_join = last_select.select_from
            found_events = False
            while last_join is not None:
                if isinstance(last_join.table, ast.Field):
                    if last_join.table.chain == ["events"]:
                        found_events = True
                        break
                last_join = last_join.next_join

            if not found_events:
                raise HogQLException(
                    "Cannot use 'filters' placeholder in a SELECT clause that does not select from the events table."
                )

            exprs: List[ast.Expr] = []
            if self.filters.properties is not None:
                exprs.append(property_to_expr(self.filters.properties, self.team))

            dateTo = self.filters.dateRange.date_to if self.filters.dateRange else None
            if dateTo is not None:
                try:
                    parsed_date = isoparse(dateTo)
                except ValueError:
                    parsed_date = relative_date_parse(dateTo, self.team.timezone_info)
                exprs.append(
                    parse_expr(
                        "timestamp < {timestamp}",
                        {"timestamp": ast.Constant(value=parsed_date)},
                        start=None,  # do not add location information for "timestamp" to the metadata
                    )
                )

            # limit to the last 30d by default
            dateFrom = self.filters.dateRange.date_from if self.filters.dateRange else None
            if dateFrom is not None and dateFrom != "all":
                try:
                    parsed_date = isoparse(dateFrom)
                except ValueError:
                    parsed_date = relative_date_parse(dateFrom, self.team.timezone_info)
                exprs.append(
                    parse_expr(
                        "timestamp >= {timestamp}",
                        {"timestamp": ast.Constant(value=parsed_date)},
                        start=None,  # do not add location information for "timestamp" to the metadata
                    )
                )

            if self.filters.filterTestAccounts:
                for prop in self.team.test_account_filters or []:
                    exprs.append(property_to_expr(prop, self.team))

            if len(exprs) == 0:
                return ast.Constant(value=True)
            if len(exprs) == 1:
                return exprs[0]
            return ast.And(exprs=exprs)
        return super().visit_placeholder(node)
