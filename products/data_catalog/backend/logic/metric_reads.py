from collections.abc import Collection
from uuid import UUID

from ..facade.contracts import HogQLMetricDefinition, MetricRead, MetricSummary
from ..facade.enums import HOGQL_DEFINITION_KIND
from ..models import Metric


def _summary(metric: Metric) -> MetricSummary:
    return MetricSummary(
        id=metric.id,
        name=metric.name,
        display_name=metric.display_name,
        definition_kind=metric.definition_kind,
        referenced_table_names=metric.referenced_table_names,
    )


def get_metric_summary(team_id: int, metric_id: UUID) -> MetricSummary | None:
    metric = Metric.objects.for_team(team_id).filter(id=metric_id, deleted=False).first()
    return _summary(metric) if metric is not None else None


def get_hogql_metric_definition(team_id: int, metric_id: UUID) -> HogQLMetricDefinition | None:
    read = metric_reads_for_ids(team_id, [metric_id]).get(metric_id)
    return read.hogql_definition if read is not None else None


def _hogql_definition(metric: Metric) -> HogQLMetricDefinition | None:
    if metric.definition_kind != HOGQL_DEFINITION_KIND or not isinstance(metric.definition, dict):
        return None

    query = metric.definition.get("query")
    # `values` is optional on HogQLQuery, so a stored null means the query takes no globals, the same
    # as an absent key. Any other type is a definition this cannot run, so it still fails below.
    values = metric.definition.get("values")
    if values is None:
        values = {}
    if not isinstance(query, str) or not isinstance(values, dict):
        return None

    return HogQLMetricDefinition(query=query, values=values.copy())


def metric_reads_for_ids(team_id: int, metric_ids: Collection[UUID]) -> dict[UUID, MetricRead]:
    if not metric_ids:
        return {}
    metrics = Metric.objects.for_team(team_id).filter(id__in=set(metric_ids), deleted=False)
    return {
        metric.id: MetricRead(summary=_summary(metric), hogql_definition=_hogql_definition(metric))
        for metric in metrics
    }


def live_metric_summaries(team_id: int) -> list[MetricSummary]:
    metrics = Metric.objects.for_team(team_id).filter(deleted=False).order_by("created_at", "id")
    return [_summary(metric) for metric in metrics]


def metric_names_for_ids(team_id: int, metric_ids: Collection[UUID]) -> dict[UUID, str]:
    """The current name of each of these metrics, as one query. A deleted or missing one is absent.

    Reads two columns of the named rows, so a caller that only needs to label a metric never
    hydrates a definition or the free text beside it.
    """
    if not metric_ids:
        return {}
    rows = Metric.objects.for_team(team_id).filter(id__in=list(metric_ids), deleted=False).values_list("id", "name")
    return dict(rows)
