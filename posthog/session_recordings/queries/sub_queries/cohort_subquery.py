from posthog.schema import FilterLogicalOperator, PropertyGroupFilterValue, RecordingsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr

from posthog.models import Team
from posthog.session_recordings.queries.sub_queries.base_query import SessionRecordingsListingBaseQuery
from posthog.session_recordings.queries.utils import is_cohort_property


class CohortPropertyGroupsSubQuery(SessionRecordingsListingBaseQuery):
    raw_cohort_to_distinct_id = """
    SELECT
        distinct_id
    FROM (
        SELECT
            distinct_id,
            argMax(person_id, version) as person_id,
            argMax(is_deleted, version) as is_deleted
        FROM raw_person_distinct_ids
        WHERE team_id = {team_id}
        GROUP BY distinct_id
        HAVING is_deleted = 0 AND {cohort_predicate}
    )
        """

    def __init__(self, team: Team, query: RecordingsQuery):
        super().__init__(team, query)

    def get_query(self) -> ast.SelectQuery | ast.SelectSetQuery | None:
        if self.cohort_properties:
            return parse_select(
                self.raw_cohort_to_distinct_id,
                {
                    "team_id": ast.Constant(value=self._team.pk),
                    "cohort_predicate": property_to_expr(self.cohort_properties, team=self._team, scope="replay"),
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
