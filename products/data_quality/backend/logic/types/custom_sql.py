from pydantic import Field, field_validator

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.metadata import get_table_names
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders

from ...facade.enums import CheckType
from ..contracts import CheckPlan, SubjectRef
from ..errors import CheckConfigError
from ..spec import CheckConfig, CheckTypeSpec


def parse_failing_rows_query(query: str) -> ast.SelectQuery | ast.SelectSetQuery:
    """Parse user HogQL into the SELECT whose rows are the failures.

    A UNION of selects is as good as one: the compiler aggregates over whatever this returns, so the
    failure set can be assembled from several branches.
    """
    try:
        parsed = parse_select(query.rstrip(";").strip())
    except ExposedHogQLError as err:
        raise CheckConfigError(f"Could not parse the custom query: {err}")
    except Exception:
        raise CheckConfigError("Could not parse the custom query.")

    found = find_placeholders(parsed)
    if found.has_filters or found.placeholder_fields or found.placeholder_expressions:
        raise CheckConfigError("A custom_sql check cannot use {placeholders} -- nothing supplies them.")
    return parsed


class CustomSqlConfig(CheckConfig):
    query: str = Field(
        min_length=1,
        description="HogQL SELECT returning one row per failure. Passing means it returns nothing.",
    )

    @field_validator("query")
    @classmethod
    def _is_a_select(cls, value: str) -> str:
        parse_failing_rows_query(value)
        return value


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
    description = "Fails on every row the custom HogQL SELECT returns."

    def referenced_table_names(self, config: CheckConfig) -> list[str]:
        assert isinstance(config, CustomSqlConfig)
        return get_table_names(parse_failing_rows_query(config.query))

    def build(
        self, subject: SubjectRef, column_name: str, config: CheckConfig, related: SubjectRef | None = None
    ) -> CheckPlan:
        assert isinstance(config, CustomSqlConfig)
        return CheckPlan(failing_rows=parse_failing_rows_query(config.query))


SPEC = CustomSqlSpec()
