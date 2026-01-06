from posthog.schema import FilterLogicalOperator, PropertyGroupFilterValue, RecordingsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr

from posthog.models import Team
from posthog.session_recordings.queries.sub_queries.base_query import SessionRecordingsListingBaseQuery
from posthog.session_recordings.queries.utils import is_person_property, poe_is_active


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

    @property
    def person_properties(self) -> PropertyGroupFilterValue | None:
        person_property_groups = [g for g in (self._query.properties or []) if is_person_property(g)]
        return (
            PropertyGroupFilterValue(
                type=FilterLogicalOperator.AND_ if self.property_operand == "AND" else FilterLogicalOperator.OR_,
                values=person_property_groups,
            )
            if person_property_groups
            else None
        )

    @property
    def _where_predicates(self) -> ast.Expr:
        return (
            property_to_expr(self.person_properties, team=self._team)
            if self.person_properties
            else ast.Constant(value=True)
        )

    def get_person_property_expr_for_replay_table(self) -> ast.Expr | None:
        """
        Returns a person property expression that can be applied directly to session_replay_events table.
        This is used when PoE is enabled to filter recordings by person properties on the replay table itself,
        rather than relying only on the events subquery which may miss recordings.
        """
        if not self.person_properties:
            return None

        return property_to_expr(self.person_properties, team=self._team, scope="replay")
