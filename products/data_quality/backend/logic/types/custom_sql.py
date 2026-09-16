from pydantic import Field

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders

from ...facade.enums import CheckType, SubjectType
from ..contracts import CheckPlan, SubjectRef
from ..errors import CheckConfigError
from ..metric_query import bind_metric_query
from ..query_scope import referenced_table_names as query_table_names
from ..spec import CheckConfig, CheckTypeSpec


def parse_failing_rows_query(query: str) -> ast.SelectQuery | ast.SelectSetQuery:
    """Parse user HogQL into the SELECT whose rows are the failures.

    A UNION of selects is as good as one: the compiler aggregates over whatever this returns, so the
    failure set can be assembled from several branches.
    """
    parsed = parse_custom_sql_query(query)

    found = find_placeholders(parsed)
    if found.has_filters or found.placeholder_fields or found.placeholder_expressions:
        raise CheckConfigError("A custom_sql check cannot use {placeholders} -- nothing supplies them.")
    return parsed


def parse_custom_sql_query(query: str) -> ast.SelectQuery | ast.SelectSetQuery:
    try:
        return parse_select(query.rstrip(";").strip())
    except ExposedHogQLError as err:
        raise CheckConfigError(f"Could not parse the custom query: {err}")
    except Exception:
        raise CheckConfigError("Could not parse the custom query.")


def build_failing_rows(subject: SubjectRef | None, config: "CustomSqlConfig") -> ast.SelectQuery | ast.SelectSetQuery:
    if subject is None or subject.subject_type != SubjectType.METRIC:
        return parse_failing_rows_query(config.query)
    if subject.metric_definition is None:
        raise CheckConfigError("Metric checks require a live HogQL definition.")
    return bind_metric_query(config.query, subject.metric_definition)


class CustomSqlConfig(CheckConfig):
    query: str = Field(
        min_length=1,
        description=(
            "HogQL SELECT returning one row per failure. Passing means it returns nothing. "
            "Metric checks must use {metric} once as a relation."
        ),
    )


class CustomSqlSpec(CheckTypeSpec):
    """A user-written HogQL SELECT whose returned rows are the failures.

    No extra sandboxing: HogQL is already team-scoped and read-only, and the query is wrapped in a
    count so rows never leave ClickHouse. Placeholders are rejected because nothing supplies them.

    Nothing forces the query to read the check's own subject -- the subject decides when the check
    runs and where its result is reported, not what the SQL may touch. A check whose query reads
    elsewhere is therefore possible, and reports against the wrong table.
    """

    type_name = CheckType.CUSTOM_SQL
    config_model = CustomSqlConfig
    requires_column = False
    subject_types = frozenset({SubjectType.TABLE, SubjectType.VIEW, SubjectType.METRIC})
    reads_beyond_subject = True
    description = "Fails on every row the custom HogQL SELECT returns. Metric checks query the {metric} relation."

    def referenced_table_names(self, config: CheckConfig, subject: SubjectRef | None = None) -> list[str]:
        assert isinstance(config, CustomSqlConfig)
        return query_table_names(build_failing_rows(subject, config))

    def build(
        self, subject: SubjectRef, column_name: str, config: CheckConfig, related: SubjectRef | None = None
    ) -> CheckPlan:
        assert isinstance(config, CustomSqlConfig)
        failing_rows = build_failing_rows(subject, config)
        query_table_names(failing_rows)
        return CheckPlan(failing_rows=failing_rows)


SPEC = CustomSqlSpec()
