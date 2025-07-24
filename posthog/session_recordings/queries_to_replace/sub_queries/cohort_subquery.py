from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.models import Team
from posthog.schema import RecordingsQuery, PropertyGroupFilterValue, FilterLogicalOperator
from posthog.session_recordings.queries_to_replace.utils import is_cohort_property
from posthog.session_recordings.queries_to_replace.sub_queries.base_query import SessionRecordingsListingBaseQuery


class CohortPropertyGroupsSubQuery(SessionRecordingsListingBaseQuery):
    raw_cohort_to_distinct_id = """
    SELECT
    distinct_id
FROM raw_person_distinct_ids
WHERE distinct_id in (SELECT distinct_id FROM raw_person_distinct_ids WHERE 1=1 AND {cohort_predicate})
GROUP BY distinct_id
HAVING argMax(is_deleted, version) = 0 AND {cohort_predicate}
    """

    def __init__(self, team: Team, query: RecordingsQuery):
        super().__init__(team, query)

    def get_query(self) -> ast.SelectQuery | ast.SelectSetQuery | None:
        if self.cohort_properties:
            return parse_select(
                self.raw_cohort_to_distinct_id,
                {"cohort_predicate": property_to_expr(self.cohort_properties, team=self._team, scope="replay")},
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
