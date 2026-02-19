from posthog.schema import (
    CohortPropertyFilter,
    FilterLogicalOperator,
    PropertyGroupFilterValue,
    PropertyOperator,
    RecordingsQuery,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.models import Cohort, Team
from posthog.session_recordings.queries.sub_queries.base_query import SessionRecordingsListingBaseQuery
from posthog.session_recordings.queries.utils import is_cohort_property


def _get_cohort_filter_info(prop: CohortPropertyFilter) -> tuple[int, bool]:
    """
    Extract cohort ID and whether it's a NOT IN filter from a cohort property filter.
    Returns (cohort_id, is_negated).
    """
    is_negated = prop.operator == PropertyOperator.NOT_IN
    return (prop.value, is_negated)


class CohortPropertyGroupsSubQuery(SessionRecordingsListingBaseQuery):
    """
    Builds a subquery that filters distinct_ids based on cohort membership.

    Uses LEFT JOIN instead of IN/NOT IN subqueries for better performance with large datasets.
    The IN/NOT IN pattern causes ClickHouse to load all cohort member IDs into RAM,
    which can cause OOM errors for large cohorts or when filtering "NOT IN" a small cohort
    against a large user base.

    The JOIN-based approach allows ClickHouse to use more efficient join algorithms
    (hash join, merge join) and doesn't require loading all IDs into memory upfront.
    """

    def __init__(self, team: Team, query: RecordingsQuery):
        super().__init__(team, query)

    def get_query(self) -> ast.SelectQuery | ast.SelectSetQuery | None:
        cohort_filters = self._extract_cohort_filters()
        if not cohort_filters:
            return None

        return self._build_join_based_query(cohort_filters)

    def _extract_cohort_filters(self) -> list[tuple[int, bool, bool, int]]:
        """
        Extract cohort filter info from query properties.
        Returns list of (cohort_id, is_negated, is_static, version) tuples.
        """
        cohort_filters: list[tuple[int, bool, bool, int]] = []

        for prop in self._query.properties or []:
            if not isinstance(prop, CohortPropertyFilter):
                continue

            cohort_id, is_negated = _get_cohort_filter_info(prop)

            # Look up cohort to determine if it's static and get version
            try:
                cohort = Cohort.objects.get(id=cohort_id, team__project_id=self._team.project_id, deleted=False)
                is_static = cohort.is_static
                version = cohort.version or 0
                cohort_filters.append((cohort_id, is_negated, is_static, version))
            except Cohort.DoesNotExist:
                # Skip invalid cohorts
                continue

        return cohort_filters

    def _build_join_based_query(
        self, cohort_filters: list[tuple[int, bool, bool, int]]
    ) -> ast.SelectQuery | ast.SelectSetQuery | None:
        """
        Build a query that uses LEFT JOINs instead of IN/NOT IN subqueries.

        For IN cohort: LEFT JOIN and filter WHERE cohort.matched = 1
        For NOT IN cohort: LEFT JOIN and filter WHERE cohort.matched != 1

        The key is to filter by team_id and cohort_id INSIDE the subquery,
        and only JOIN ON person_id. This avoids ClickHouse's limitations
        with complex JOIN ON conditions.
        """
        if not cohort_filters:
            return None

        # Build the join subqueries and conditions
        join_clauses: list[str] = []
        where_conditions: list[str] = []

        for idx, (cohort_id, is_negated, is_static, version) in enumerate(cohort_filters):
            alias = f"cohort_{idx}"

            # Build a subquery that filters by team_id, cohort_id (and version for dynamic)
            # inside the subquery, then JOIN only on person_id
            # Note: Use HogQL table names (static_cohort_people, raw_cohort_people),
            # not ClickHouse table names (person_static_cohort, cohortpeople)
            if is_static:
                # Static cohorts don't have version
                subquery = (
                    f"(SELECT person_id, 1 AS matched FROM static_cohort_people "
                    f"WHERE team_id = {self._team.pk} AND cohort_id = {cohort_id})"
                )
            else:
                # Dynamic cohorts need version check
                subquery = (
                    f"(SELECT person_id, 1 AS matched FROM raw_cohort_people "
                    f"WHERE team_id = {self._team.pk} AND cohort_id = {cohort_id} AND version = {version})"
                )

            # JOIN only on person_id - the filtering is done inside the subquery
            join_clauses.append(f"LEFT JOIN {subquery} AS {alias} ON {alias}.person_id = pdi.person_id")

            # Add the WHERE condition based on IN vs NOT IN
            if is_negated:
                # NOT IN cohort: matched should be NULL or != 1
                where_conditions.append(f"ifNull({alias}.matched, 0) != 1")
            else:
                # IN cohort: matched should be 1
                where_conditions.append(f"{alias}.matched = 1")

        if not join_clauses or not where_conditions:
            return None

        # Combine conditions based on the property operand (AND vs OR)
        if self.property_operand == "AND":
            combined_where = " AND ".join(where_conditions)
        else:
            combined_where = " OR ".join(f"({cond})" for cond in where_conditions)

        joins_sql = " ".join(join_clauses)

        # Build the full query using LEFT JOINs
        query_template = f"""
        SELECT
            pdi.distinct_id AS distinct_id
        FROM (
            SELECT
                distinct_id,
                argMax(person_id, version) AS person_id,
                argMax(is_deleted, version) AS is_deleted
            FROM raw_person_distinct_ids
            WHERE team_id = {{team_id}}
            GROUP BY distinct_id
            HAVING is_deleted = 0
        ) AS pdi
        {joins_sql}
        WHERE {combined_where}
        """

        return parse_select(
            query_template,
            {
                "team_id": ast.Constant(value=self._team.pk),
            },
        )

    @property
    def cohort_properties(self) -> PropertyGroupFilterValue | None:
        """Legacy property for backwards compatibility."""
        cohort_property_groups = [g for g in (self._query.properties or []) if is_cohort_property(g)]
        return (
            PropertyGroupFilterValue(
                type=FilterLogicalOperator.AND_ if self.property_operand == "AND" else FilterLogicalOperator.OR_,
                values=cohort_property_groups,
            )
            if cohort_property_groups
            else None
        )
