from typing import cast

from posthog.schema import PropertyGroupFilterValue, PropertyOperator, RecordingsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr

from posthog.constants import PropertyOperatorType
from posthog.models import Team
from posthog.session_recordings.queries.sub_queries.base_query import SessionRecordingsListingBaseQuery
from posthog.session_recordings.queries.utils import (
    INVERSE_OPERATOR_FOR,
    is_negative_prop,
    is_person_property,
    poe_is_active,
)
from posthog.types import AnyPropertyFilter


class PersonsPropertiesSubQuery(SessionRecordingsListingBaseQuery):
    def __init__(self, team: Team, query: RecordingsQuery):
        super().__init__(team, query)

    def get_query(self) -> ast.SelectQuery | ast.SelectSetQuery | None:
        if self.person_properties and not poe_is_active(self._team):
            return parse_select(
                """
                SELECT distinct_id
                FROM person_distinct_ids
                WHERE {where_predicates}
                """,
                {
                    "where_predicates": self._where_predicates,
                },
            )
        else:
            return None

    def get_blocked_distinct_ids_query(self, distinct_ids: list[str]) -> ast.SelectQuery | ast.SelectSetQuery | None:
        """Which of `distinct_ids` resolve to a person that a negative person-property filter excludes.

        In PoE mode negative person filters ride on the events-table blocklist, so a session with
        no events is never excluded, even when its person matches the excluded value. This scoped
        check reads the person record through the distinct id, so it needs no events. It follows
        the blocklist's rules: negative filters only, AND operand only. It tests the person's
        current properties, where the events path tests the properties at event time.
        """
        if not distinct_ids or not poe_is_active(self._team):
            return None
        if self.property_operand != PropertyOperatorType.AND:
            return None

        negative_props = [p for p in self._person_property_filters if is_negative_prop(p)]
        if not negative_props:
            return None

        blocked_exprs: list[ast.Expr] = []
        for prop in negative_props:
            operator = cast(PropertyOperator, prop.operator)  # type: ignore[union-attr]
            inverted = prop.model_copy(update={"operator": INVERSE_OPERATOR_FOR[operator]})
            blocked_exprs.append(property_to_expr(inverted, team=self._team))

        # A person matching any one positive form is excluded, so the inverted filters combine with OR.
        blocked = ast.Or(exprs=blocked_exprs) if len(blocked_exprs) > 1 else blocked_exprs[0]

        return parse_select(
            """
            SELECT distinct_id
            FROM person_distinct_ids
            WHERE distinct_id IN {distinct_ids} AND {blocked}
            """,
            {
                "distinct_ids": ast.Constant(value=distinct_ids),
                "blocked": blocked,
            },
        )

    @property
    def _person_property_filters(self) -> list[AnyPropertyFilter]:
        return [g for g in (self._query.properties or []) if is_person_property(g)]

    @property
    def person_properties(self) -> PropertyGroupFilterValue | None:
        person_property_groups = self._person_property_filters
        return self.property_group_with_operand(person_property_groups) if person_property_groups else None

    @property
    def _where_predicates(self) -> ast.Expr:
        return (
            property_to_expr(self.person_properties, team=self._team)
            if self.person_properties
            else ast.Constant(value=True)
        )
