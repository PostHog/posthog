from posthog.schema import CohortPropertyFilter, PropertyOperator, RecordingsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.models import Cohort, Team
from posthog.session_recordings.queries.sub_queries.base_query import SessionRecordingsListingBaseQuery


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

            cohort_id = prop.value
            is_negated = prop.operator == PropertyOperator.NOT_IN

            try:
                cohort = Cohort.objects.get(id=cohort_id, team__project_id=self._team.project_id, deleted=False)
                cohort_filters.append((cohort_id, is_negated, cohort.is_static, cohort.version or 0))
            except Cohort.DoesNotExist:
                continue

        return cohort_filters

    def _build_join_based_query(
        self, cohort_filters: list[tuple[int, bool, bool, int]]
    ) -> ast.SelectQuery | ast.SelectSetQuery | None:
        """
        Build a query that uses LEFT JOINs instead of IN/NOT IN subqueries.

        For IN cohort: LEFT JOIN and filter WHERE cohort.matched = 1
        For NOT IN cohort: LEFT JOIN and filter WHERE cohort.matched != 1

        Filters by cohort_id (and version for dynamic) inside the subquery,
        joins only on person_id. HogQL automatically adds team_id filtering.
        """
        join_clauses: list[str] = []
        where_conditions: list[str] = []
        placeholders: dict[str, ast.Expr] = {
            "team_id": ast.Constant(value=self._team.pk),
        }

        for idx, (cohort_id, is_negated, is_static, version) in enumerate(cohort_filters):
            alias = f"cohort_{idx}"
            cohort_id_placeholder = f"cohort_id_{idx}"
            placeholders[cohort_id_placeholder] = ast.Constant(value=cohort_id)

            # HogQL automatically adds team_id filter, so we only need cohort_id (and version)
            if is_static:
                subquery = f"(SELECT person_id, 1 AS matched FROM static_cohort_people WHERE cohort_id = {{{cohort_id_placeholder}}})"
            else:
                version_placeholder = f"version_{idx}"
                placeholders[version_placeholder] = ast.Constant(value=version)
                subquery = f"(SELECT person_id, 1 AS matched FROM raw_cohort_people WHERE cohort_id = {{{cohort_id_placeholder}}} AND version = {{{version_placeholder}}})"

            join_clauses.append(f"LEFT JOIN {subquery} AS {alias} ON {alias}.person_id = pdi.person_id")

            if is_negated:
                where_conditions.append(f"ifNull({alias}.matched, 0) != 1")
            else:
                where_conditions.append(f"{alias}.matched = 1")

        if self.property_operand == "AND":
            combined_where = " AND ".join(where_conditions)
        else:
            combined_where = " OR ".join(f"({cond})" for cond in where_conditions)

        query_template = f"""
        SELECT pdi.distinct_id AS distinct_id
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
        {" ".join(join_clauses)}
        WHERE {combined_where}
        """

        return parse_select(query_template, placeholders)
