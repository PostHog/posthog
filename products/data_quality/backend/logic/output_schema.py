from collections.abc import Sequence
from uuid import UUID

from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.errors import ExposedCHQueryError
from posthog.models import Team, User

from ..facade.contracts import OutputColumn
from ..facade.enums import SubjectType
from .errors import CheckConfigError, SubjectUnresolvableError
from .metric_query import bind_metric_query
from .subjects import resolve_subject

_SCHEMA_QUERY = "SELECT * FROM {metric} LIMIT 0"


def metric_output_schema(team: Team, metric_id: str | UUID, user: User) -> list[OutputColumn]:
    subject = resolve_subject(team.id, SubjectType.METRIC, metric_id)
    if not subject.exists:
        raise SubjectUnresolvableError("The metric no longer resolves.")
    if subject.metric_definition is None:
        raise CheckConfigError("Only HogQL metrics can be tested.")

    query = bind_metric_query(_SCHEMA_QUERY, subject.metric_definition)
    try:
        with tags_context(product=Product.DATA_QUALITY, feature=Feature.QUERY):
            response = execute_hogql_query(
                query=query,
                team=team,
                user=user,
                query_type="data_quality_metric_output_schema",
            )
    except (ExposedHogQLError, ExposedCHQueryError) as error:
        raise CheckConfigError(f"Could not load the metric output schema: {error}")

    if response.error:
        raise CheckConfigError(f"Could not load the metric output schema: {response.error}")
    return _output_columns(response.columns, response.types)


def _output_columns(
    names: Sequence[str] | None,
    types: Sequence[str | tuple[str, str]] | None,
) -> list[OutputColumn]:
    return [OutputColumn(name=name, type=_type_at(types, index)) for index, name in enumerate(names or [])]


def _type_at(types: Sequence[str | tuple[str, str]] | None, index: int) -> str | None:
    if types is None or index >= len(types):
        return None
    entry = types[index]
    if isinstance(entry, str):
        return entry
    return str(entry[1])
