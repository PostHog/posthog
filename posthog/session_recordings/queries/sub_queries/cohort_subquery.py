from posthog.schema import FilterLogicalOperator, PropertyGroupFilterValue, RecordingsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.visitor import CloningVisitor

from posthog.models import Team
from posthog.session_recordings.queries.sub_queries.base_query import SessionRecordingsListingBaseQuery
from posthog.session_recordings.queries.utils import is_cohort_property


class TablePrefixVisitor(CloningVisitor):
    """Adds table alias prefix to person_id and distinct_id field references."""

    def __init__(self, table_alias: str):
        super().__init__()
        self.table_alias = table_alias

    def visit_field(self, node: ast.Field) -> ast.Field:
        # If the field is just "person_id" or "distinct_id", add the table alias prefix
        if node.chain == ["person_id"] or node.chain == ["distinct_id"]:
            return ast.Field(chain=[self.table_alias, *node.chain])
        return node


class CohortPropertyGroupsSubQuery(SessionRecordingsListingBaseQuery):
    raw_cohort_to_distinct_id = """
    SELECT
        distinct_id
    FROM (
        SELECT
            pdi.distinct_id as distinct_id,
            argMax(pdi.person_id, pdi.version) as person_id,
            argMax(pdi.is_deleted, pdi.version) as is_deleted
        FROM raw_person_distinct_ids as pdi
        WHERE pdi.team_id = {team_id}
        AND {cohort_predicate}
        GROUP BY pdi.distinct_id
        HAVING is_deleted = 0
    )
        """

    def __init__(self, team: Team, query: RecordingsQuery):
        super().__init__(team, query)

    def get_query(self) -> ast.SelectQuery | ast.SelectSetQuery | None:
        if self.cohort_properties:
            cohort_predicate = property_to_expr(self.cohort_properties, team=self._team, scope="replay")

            # Add table alias prefix to person_id references in the predicate.
            # This is necessary to avoid ClickHouse trying to use the argMax(person_id, version)
            # aggregate result in the WHERE clause, which causes an ILLEGAL_AGGREGATION error.
            # By prefixing with 'pdi', we ensure it references the raw column pdi.person_id instead.
            visitor = TablePrefixVisitor("pdi")
            cohort_predicate_with_prefix = visitor.visit(cohort_predicate)

            return parse_select(
                self.raw_cohort_to_distinct_id,
                {
                    "team_id": ast.Constant(value=self._team.pk),
                    "cohort_predicate": cohort_predicate_with_prefix,
                },
            )

        return None

    @property
    def cohort_properties(self) -> PropertyGroupFilterValue | None:
        cohort_property_groups = [g for g in (self._query.properties or []) if is_cohort_property(g)]
        return (
            PropertyGroupFilterValue(
                type=FilterLogicalOperator.AND_ if self.property_operand == "AND" else FilterLogicalOperator.OR_,
                values=cohort_property_groups,
            )
            if cohort_property_groups
            else None
        )
