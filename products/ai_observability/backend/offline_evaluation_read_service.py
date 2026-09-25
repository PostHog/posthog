from __future__ import annotations

import json
import hashlib
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID

from django.db import connections
from django.db.models import Count, Exists, F, OuterRef, Q

from posthog.dataclasses import frozen

from products.ai_observability.backend.models.offline_evaluations import (
    OfflineEvaluationResult,
    OfflineEvaluationResultPayload,
    OfflineExperiment,
    OfflineExperimentItem,
    OfflineExperimentItemPayload,
    PayloadState,
)
from products.ai_observability.backend.models.score_definitions import ScoreDefinition, ScoreDefinitionVersion
from products.ai_observability.backend.offline_evaluation_read_types import (
    OfflineCategorySummary,
    OfflineExperimentRead,
    OfflineHistoryPoint,
    OfflineItemRead,
    OfflinePage,
    OfflinePayloadRead,
    OfflineReadQuery,
    OfflineResultRead,
    OfflineScorerSummary,
    OfflineScorerVersionRead,
    OfflineStatusCounts,
    decode_cursor,
    encode_cursor,
)
from products.ai_observability.backend.offline_evaluation_service import (
    OfflineEvaluationNotFound,
    OfflineEvaluationValidationError,
)
from products.ai_observability.backend.offline_evaluation_types import JSONValue, ResultValue

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from products.access_control.backend.facade.user_access_control import UserAccessControl


@frozen
class _SummaryIdentity:
    experiment_id: UUID
    version_id: UUID


@frozen
class _ItemCoverage:
    observed_item_count: int = 0
    distinct_case_count: int = 0
    items_with_case_key_count: int = 0
    items_without_case_key_count: int = 0
    trial_item_count: int = 0
    distinct_trial_count: int = 0


@frozen
class _Aggregate:
    count: int
    status_counts: OfflineStatusCounts
    mean: float | None
    true_count: int
    false_count: int
    coverage: _ItemCoverage
    categories: dict[str, int]


@frozen
class _ExperimentCounts:
    item_count: int = 0
    result_count: int = 0
    definition_count: int = 0
    version_count: int = 0


@frozen
class _TimePosition:
    started_at: datetime
    experiment_id: UUID
    version_id: UUID | None


class OfflineEvaluationReadService:
    def __init__(self, *, team_id: int, user_access_control: UserAccessControl | None, can_read_scores: bool) -> None:
        self.team_id = team_id
        self._user_access_control = user_access_control
        self.can_read_scores = can_read_scores

    def _experiments(self) -> QuerySet[OfflineExperiment]:
        return OfflineExperiment.objects.for_team(self.team_id)

    def _items(self) -> QuerySet[OfflineExperimentItem]:
        return OfflineExperimentItem.objects.for_team(self.team_id)

    def _definitions(self) -> QuerySet[ScoreDefinition]:
        definitions = ScoreDefinition.objects.filter(team_id=self.team_id)
        if not self.can_read_scores:
            return definitions.none()
        if self._user_access_control is not None:
            definitions = self._user_access_control.filter_queryset_by_access_level(
                definitions, include_all_if_admin=True, resource="llm_analytics"
            )
        return definitions

    def _versions(self) -> QuerySet[ScoreDefinitionVersion]:
        # nosemgrep: idor-lookup-without-user -- Versions inherit the authorized definitions' exact environment.
        return ScoreDefinitionVersion.objects.filter(definition__in=self._definitions())

    def _validate_scorer_selection(self, query: OfflineReadQuery) -> None:
        if (
            query.scorer_definition_id is not None
            and not self._definitions().filter(id=query.scorer_definition_id).exists()
        ):
            raise OfflineEvaluationNotFound
        if query.scorer_version_ids:
            versions = self._versions().filter(id__in=query.scorer_version_ids)
            if query.scorer_definition_id is not None:
                versions = versions.filter(definition_id=query.scorer_definition_id)
            if versions.count() != len(query.scorer_version_ids):
                raise OfflineEvaluationNotFound

    def _results(self, query: OfflineReadQuery | None = None) -> QuerySet[OfflineEvaluationResult]:
        results = OfflineEvaluationResult.objects.for_team(self.team_id).filter(
            scorer_definition__in=self._definitions()
        )
        if query is not None:
            if query.scorer_definition_id is not None:
                results = results.filter(scorer_definition_id=query.scorer_definition_id)
            if query.scorer_version_ids:
                results = results.filter(scorer_version_id__in=query.scorer_version_ids)
        return results

    def _require_experiment(self, experiment_id: UUID) -> OfflineExperiment:
        experiment = self._experiments().filter(id=experiment_id).first()
        if experiment is None:
            raise OfflineEvaluationNotFound
        return experiment

    def _require_item(self, experiment_id: UUID, item_id: UUID) -> OfflineExperimentItem:
        item = self._items().filter(experiment_id=experiment_id, id=item_id).first()
        if item is None:
            raise OfflineEvaluationNotFound
        return item

    def _filter_experiments(self, query: OfflineReadQuery, *, history: bool = False) -> QuerySet[OfflineExperiment]:
        experiments = self._experiments()
        if query.date_from is not None:
            experiments = experiments.filter(started_at__gte=query.date_from)
        if query.date_to is not None:
            experiments = experiments.filter(started_at__lt=query.date_to)
        if query.search:
            experiments = experiments.filter(name__icontains=query.search)
        if query.run_source_is_null:
            experiments = experiments.filter(run_source__isnull=True)
        elif query.run_source is not None:
            experiments = experiments.filter(run_source=query.run_source)
        if query.statuses is not None:
            experiments = experiments.filter(status__in=query.statuses)
        elif history:
            experiments = experiments.filter(status=OfflineExperiment.Status.COMPLETED)
        for field in (
            "suite_key",
            "dataset_source",
            "dataset_identifier",
            "dataset_revision_identifier",
            "application_version",
            "model_version",
            "prompt_version",
        ):
            value = getattr(query, field)
            if value is not None:
                experiments = experiments.filter(**{field: value})
        if query.scorer_definition_id is not None or query.scorer_version_ids:
            experiments = experiments.filter(Exists(self._results(query).filter(item__experiment_id=OuterRef("id"))))
        return experiments

    def _cursor_scope(self, query: OfflineReadQuery, scope: str) -> str:
        filters = asdict(query)
        filters.pop("cursor")
        filters.pop("limit")
        content = json.dumps([self.team_id, self.can_read_scores, scope, filters], default=str, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:24]

    def _cursor(self, query: OfflineReadQuery, scope: str, size: int) -> list[str] | None:
        if query.cursor is None:
            return None
        parts = decode_cursor(query.cursor, size + 1)
        if parts[0] != self._cursor_scope(query, scope):
            raise OfflineEvaluationValidationError("cursor", "This cursor does not match the requested filters.")
        return parts[1:]

    def _next_cursor(self, query: OfflineReadQuery, scope: str, values: list[str]) -> str:
        return encode_cursor([self._cursor_scope(query, scope), *values])

    def _uuid_cursor(self, query: OfflineReadQuery, scope: str) -> UUID | None:
        parts = self._cursor(query, scope, 1)
        try:
            return UUID(parts[0]) if parts is not None else None
        except ValueError as error:
            raise OfflineEvaluationValidationError("cursor", "Provide a valid continuation cursor.") from error

    def _time_cursor(self, query: OfflineReadQuery, scope: str, *, history: bool = False) -> _TimePosition | None:
        parts = self._cursor(query, scope, 3 if history else 2)
        if parts is None:
            return None
        try:
            started_at = datetime.fromisoformat(parts[0])
            if started_at.tzinfo is None:
                raise ValueError
            return _TimePosition(
                started_at=started_at, experiment_id=UUID(parts[1]), version_id=UUID(parts[2]) if history else None
            )
        except ValueError as error:
            raise OfflineEvaluationValidationError("cursor", "Provide a valid continuation cursor.") from error

    def _experiment_counts(self, experiment_ids: list[UUID]) -> dict[UUID, _ExperimentCounts]:
        if not experiment_ids:
            return {}
        if not self.can_read_scores:
            return {
                row["experiment_id"]: _ExperimentCounts(item_count=row["item_count"])
                for row in self._items()
                .filter(experiment_id__in=experiment_ids)
                .order_by()
                .values("experiment_id")
                .annotate(item_count=Count("id"))
            }
        results = (
            self._results()
            .filter(item__experiment_id__in=experiment_ids)
            .order_by()
            .annotate(experiment_id=F("item__experiment_id"))
            .values("experiment_id")
            .annotate(
                result_count=Count("id"),
                definition_count=Count("scorer_definition_id", distinct=True),
                version_count=Count("scorer_version_id", distinct=True),
            )
        )
        result_sql, params = results.query.sql_with_params()
        item_table = OfflineExperimentItem._meta.db_table
        sql = f"""
            WITH item_counts AS (
                SELECT experiment_id, count(*) AS item_count
                FROM {item_table}
                WHERE team_id = %s AND experiment_id = ANY(%s)
                GROUP BY experiment_id
            ), result_counts AS (
                {result_sql}
            )
            SELECT i.experiment_id, i.item_count, coalesce(r.result_count, 0),
                   coalesce(r.definition_count, 0), coalesce(r.version_count, 0)
            FROM item_counts i LEFT JOIN result_counts r USING (experiment_id)
        """
        with connections[results.db].cursor() as cursor:
            cursor.execute(sql, [self.team_id, experiment_ids, *params])
            return {
                row[0]: _ExperimentCounts(
                    item_count=row[1], result_count=row[2], definition_count=row[3], version_count=row[4]
                )
                for row in cursor.fetchall()
            }

    def _experiment_reads(self, experiments: list[OfflineExperiment]) -> list[OfflineExperimentRead]:
        ids = [experiment.id for experiment in experiments]
        visible_counts = self._experiment_counts(ids)
        output = []
        for experiment in experiments:
            counts = visible_counts.get(experiment.id, _ExperimentCounts())
            output.append(
                OfflineExperimentRead(
                    id=experiment.id,
                    name=experiment.name,
                    run_source=experiment.run_source,
                    status=experiment.status,
                    started_at=experiment.started_at,
                    created_at=experiment.created_at,
                    finished_at=experiment.finished_at,
                    expected_item_count=experiment.expected_item_count,
                    expected_result_count=experiment.expected_result_count,
                    accepted_item_count=counts.item_count,
                    visible_result_count=counts.result_count if self.can_read_scores else None,
                    visible_scorer_definition_count=counts.definition_count if self.can_read_scores else None,
                    visible_scorer_version_count=counts.version_count if self.can_read_scores else None,
                    result_counts_available=self.can_read_scores,
                    result_count_scope="authorized" if self.can_read_scores else "unavailable",
                    suite_key=experiment.suite_key,
                    dataset_source=experiment.dataset_source,
                    dataset_identifier=experiment.dataset_identifier,
                    dataset_revision_identifier=experiment.dataset_revision_identifier,
                    dataset_revision_id=experiment.dataset_revision_id,
                    application_version=experiment.application_version,
                    model_version=experiment.model_version,
                    prompt_version=experiment.prompt_version,
                )
            )
        return output

    def list_experiments(self, query: OfflineReadQuery) -> OfflinePage[OfflineExperimentRead]:
        self._validate_scorer_selection(query)
        scope = "experiments"
        experiments = self._filter_experiments(query)
        count = experiments.count()
        position = self._time_cursor(query, scope)
        if position is not None:
            experiments = experiments.filter(
                Q(started_at__lt=position.started_at) | Q(started_at=position.started_at, id__gt=position.experiment_id)
            )
        rows = list(experiments.order_by("-started_at", "id")[: query.limit + 1])
        page = rows[: query.limit]
        next_cursor = (
            self._next_cursor(query, scope, [page[-1].started_at.isoformat(), str(page[-1].id)])
            if len(rows) > query.limit
            else None
        )
        return OfflinePage(count=count, next_cursor=next_cursor, results=self._experiment_reads(page))

    def get_experiment(self, experiment_id: UUID) -> OfflineExperimentRead:
        return self._experiment_reads([self._require_experiment(experiment_id)])[0]

    def _version_read(self, version: ScoreDefinitionVersion) -> OfflineScorerVersionRead:
        definition = version.definition
        return OfflineScorerVersionRead(
            id=version.id,
            definition_id=definition.id,
            version=version.version,
            kind=definition.kind,
            name=definition.name,
            description=definition.description,
            archived=definition.archived,
            config=cast(dict[str, JSONValue], version.config),
        )

    def _result_read(self, result: OfflineEvaluationResult) -> OfflineResultRead:
        value: ResultValue | None = result.numeric_value
        if result.boolean_value is not None:
            value = result.boolean_value
        elif result.categorical_values is not None:
            value = result.categorical_values
        return OfflineResultRead(
            id=result.id,
            item_id=result.item_id,
            scorer=self._version_read(result.scorer_version),
            status=result.status,
            value=value,
            error_code=result.error_code,
            evaluator_trace_id=result.evaluator_trace_id,
            evaluated_at=result.evaluated_at,
            accepted_at=result.accepted_at,
            payload_state=result.payload_state,
            payload_expires_at=result.payload_expires_at,
        )

    def _item_read(
        self, item: OfflineExperimentItem, results: list[OfflineResultRead] | None = None
    ) -> OfflineItemRead:
        return OfflineItemRead(
            id=item.id,
            experiment_id=item.experiment_id,
            case_key=item.case_key,
            trial=item.trial,
            dataset_item_identifier=item.dataset_item_identifier,
            dataset_item_version_identifier=item.dataset_item_version_identifier,
            dataset_item_version_id=item.dataset_item_version_id,
            application_trace_id=item.application_trace_id,
            accepted_at=item.accepted_at,
            payload_state=item.payload_state,
            payload_expires_at=item.payload_expires_at,
            results=results or [],
        )

    def list_items(self, experiment_id: UUID, query: OfflineReadQuery) -> OfflinePage[OfflineItemRead]:
        self._require_experiment(experiment_id)
        self._validate_scorer_selection(query)
        scope = f"items:{experiment_id}"
        items = self._items().filter(experiment_id=experiment_id)
        count = items.count()
        position = self._uuid_cursor(query, scope)
        if position is not None:
            items = items.filter(id__gt=position)
        rows = list(items.order_by("id")[: query.limit + 1])
        page = rows[: query.limit]
        cells: dict[UUID, list[OfflineResultRead]] = defaultdict(list)
        if query.scorer_version_ids and page:
            results = (
                self._results(query)
                .filter(item_id__in=[item.id for item in page])
                .select_related("scorer_version__definition")
                .order_by("scorer_version_id")
            )
            for result in results:
                cells[result.item_id].append(self._result_read(result))
        next_cursor = self._next_cursor(query, scope, [str(page[-1].id)]) if len(rows) > query.limit else None
        return OfflinePage(
            count=count, next_cursor=next_cursor, results=[self._item_read(item, cells[item.id]) for item in page]
        )

    def get_item(self, experiment_id: UUID, item_id: UUID) -> OfflineItemRead:
        return self._item_read(self._require_item(experiment_id, item_id))

    def list_item_results(
        self, experiment_id: UUID, item_id: UUID, query: OfflineReadQuery
    ) -> OfflinePage[OfflineResultRead]:
        if not self.can_read_scores:
            raise OfflineEvaluationNotFound
        self._require_item(experiment_id, item_id)
        self._validate_scorer_selection(query)
        scope = f"results:{experiment_id}:{item_id}"
        results = self._results(query).filter(item_id=item_id)
        count = results.count()
        position = self._uuid_cursor(query, scope)
        if position is not None:
            results = results.filter(id__gt=position)
        rows = list(results.select_related("scorer_version__definition").order_by("id")[: query.limit + 1])
        page = rows[: query.limit]
        next_cursor = self._next_cursor(query, scope, [str(page[-1].id)]) if len(rows) > query.limit else None
        return OfflinePage(count=count, next_cursor=next_cursor, results=[self._result_read(result) for result in page])

    def get_item_payload(self, experiment_id: UUID, item_id: UUID) -> OfflinePayloadRead:
        item = self._require_item(experiment_id, item_id)
        payload = (
            OfflineExperimentItemPayload.objects.for_team(self.team_id).filter(item_id=item.id).first()
            if item.payload_state == PayloadState.AVAILABLE
            else None
        )
        return OfflinePayloadRead(
            id=item.id,
            payload_state=item.payload_state,
            payload_expires_at=item.payload_expires_at,
            available=payload is not None,
            data=payload.data if payload is not None else None,
        )

    def get_result_payload(self, experiment_id: UUID, result_id: UUID) -> OfflinePayloadRead:
        result = self._results().filter(id=result_id, item__experiment_id=experiment_id).first()
        if result is None:
            raise OfflineEvaluationNotFound
        payload = (
            OfflineEvaluationResultPayload.objects.for_team(self.team_id).filter(result_id=result.id).first()
            if result.payload_state == PayloadState.AVAILABLE
            else None
        )
        return OfflinePayloadRead(
            id=result.id,
            payload_state=result.payload_state,
            payload_expires_at=result.payload_expires_at,
            available=payload is not None,
            data=payload.data if payload is not None else None,
        )

    def _aggregates(self, identities: list[_SummaryIdentity]) -> dict[_SummaryIdentity, _Aggregate]:
        selected = Q(pk__in=[])
        for identity in identities:
            selected |= Q(item__experiment_id=identity.experiment_id, scorer_version_id=identity.version_id)
        results = (
            self._results()
            .filter(selected)
            .order_by()
            .annotate(experiment_id=F("item__experiment_id"))
            .values(
                "experiment_id", "scorer_version_id", "status", "numeric_value", "boolean_value", "categorical_values"
            )
        )
        sql, params = results.query.sql_with_params()
        item_table = OfflineExperimentItem._meta.db_table
        # The text conversion preserves float precision before numeric accumulation prevents overflow.
        aggregate_sql = f"""
            WITH selected AS (
                {sql}
            ), aggregates AS (
                SELECT experiment_id, scorer_version_id, count(*) AS result_count,
                       count(*) FILTER (WHERE status = 'ok') AS ok_count,
                       count(*) FILTER (WHERE status = 'error') AS error_count,
                       count(*) FILTER (WHERE status = 'skipped') AS skipped_count,
                       count(*) FILTER (WHERE status = 'not_applicable') AS not_applicable_count,
                       avg(numeric_value::text::numeric) FILTER (WHERE status = 'ok') AS mean,
                       count(*) FILTER (WHERE status = 'ok' AND boolean_value IS TRUE) AS true_count,
                       count(*) FILTER (WHERE status = 'ok' AND boolean_value IS FALSE) AS false_count
                FROM selected GROUP BY experiment_id, scorer_version_id
            ), category_counts AS (
                SELECT experiment_id, scorer_version_id, category, count(*) AS selected_count
                FROM selected CROSS JOIN LATERAL unnest(categorical_values) AS category
                WHERE status = 'ok'
                GROUP BY experiment_id, scorer_version_id, category
            ), categories AS (
                SELECT experiment_id, scorer_version_id,
                       array_agg(category ORDER BY category) AS keys,
                       array_agg(selected_count ORDER BY category) AS counts
                FROM category_counts GROUP BY experiment_id, scorer_version_id
            ), coverage AS (
                SELECT experiment_id, count(*) AS observed_item_count, count(DISTINCT case_key) AS distinct_case_count,
                       count(*) FILTER (WHERE case_key IS NOT NULL) AS items_with_case_key_count,
                       count(*) FILTER (WHERE case_key IS NULL) AS items_without_case_key_count,
                       count(*) FILTER (WHERE trial IS NOT NULL) AS trial_item_count,
                       count(DISTINCT (case_key, CASE WHEN case_key IS NULL THEN id END, trial))
                           FILTER (WHERE trial IS NOT NULL) AS distinct_trial_count
                FROM {item_table}
                WHERE team_id = %s AND experiment_id = ANY(%s)
                GROUP BY experiment_id
            )
            SELECT a.experiment_id, a.scorer_version_id, a.result_count, a.ok_count, a.error_count,
                   a.skipped_count, a.not_applicable_count, a.mean, a.true_count, a.false_count,
                   c.observed_item_count, c.distinct_case_count, c.items_with_case_key_count,
                   c.items_without_case_key_count, c.trial_item_count, c.distinct_trial_count,
                   categories.keys, categories.counts
            FROM aggregates a JOIN coverage c USING (experiment_id)
            LEFT JOIN categories USING (experiment_id, scorer_version_id)
        """
        # One statement keeps coverage and category denominators coherent during uploads.
        with connections[results.db].cursor() as cursor:
            cursor.execute(
                aggregate_sql,
                [
                    *params,
                    self.team_id,
                    list({identity.experiment_id for identity in identities}),
                ],
            )
            return {
                _SummaryIdentity(experiment_id=row[0], version_id=row[1]): _Aggregate(
                    count=row[2],
                    status_counts=OfflineStatusCounts(ok=row[3], error=row[4], skipped=row[5], not_applicable=row[6]),
                    # Python rounds underflow to zero; PostgreSQL's float cast rejects it.
                    mean=float(row[7]) if row[7] is not None else None,
                    true_count=row[8],
                    false_count=row[9],
                    coverage=_ItemCoverage(
                        observed_item_count=row[10],
                        distinct_case_count=row[11],
                        items_with_case_key_count=row[12],
                        items_without_case_key_count=row[13],
                        trial_item_count=row[14],
                        distinct_trial_count=row[15],
                    ),
                    categories=dict(zip(row[16] or [], row[17] or [])),
                )
                for row in cursor.fetchall()
            }

    def _summaries(self, identities: list[_SummaryIdentity]) -> dict[_SummaryIdentity, OfflineScorerSummary]:
        if not identities:
            return {}
        versions = {
            version.id: version
            for version in self._versions()
            .filter(id__in=[identity.version_id for identity in identities])
            .select_related("definition")
        }
        aggregates = self._aggregates(identities)
        summaries = {}
        for identity in identities:
            version = versions.get(identity.version_id)
            aggregate = aggregates.get(identity)
            if version is None or aggregate is None:
                continue
            scorer = self._version_read(version)
            counts = aggregate.coverage
            categories = []
            if scorer.kind == "categorical":
                options = scorer.config.get("options")
                for option in options if isinstance(options, list) else []:
                    if isinstance(option, dict) and isinstance(option.get("key"), str):
                        key = cast(str, option["key"])
                        count = aggregate.categories.get(key, 0)
                        categories.append(
                            OfflineCategorySummary(
                                key=key,
                                label=str(option.get("label", key)),
                                count=count,
                                rate=count / aggregate.status_counts.ok if aggregate.status_counts.ok else None,
                            )
                        )
            summaries[identity] = OfflineScorerSummary(
                scorer=scorer,
                observed_item_count=counts.observed_item_count,
                result_count=aggregate.count,
                status_counts=aggregate.status_counts,
                missing_result_count=counts.observed_item_count - aggregate.count,
                distinct_case_count=counts.distinct_case_count,
                items_with_case_key_count=counts.items_with_case_key_count,
                items_without_case_key_count=counts.items_without_case_key_count,
                trial_item_count=counts.trial_item_count,
                distinct_trial_count=counts.distinct_trial_count,
                mean=aggregate.mean,
                true_count=aggregate.true_count if scorer.kind == "boolean" else None,
                false_count=aggregate.false_count if scorer.kind == "boolean" else None,
                true_rate=aggregate.true_count / aggregate.status_counts.ok
                if scorer.kind == "boolean" and aggregate.status_counts.ok
                else None,
                categories=categories,
            )
        return summaries

    def list_summaries(self, experiment_id: UUID, query: OfflineReadQuery) -> OfflinePage[OfflineScorerSummary]:
        if not self.can_read_scores:
            raise OfflineEvaluationNotFound
        self._require_experiment(experiment_id)
        self._validate_scorer_selection(query)
        scope = f"summaries:{experiment_id}"
        results = self._results(query).filter(item__experiment_id=experiment_id)
        groups = results.order_by("scorer_version_id").values_list("scorer_version_id", flat=True).distinct()
        count = groups.count()
        position = self._uuid_cursor(query, scope)
        if position is not None:
            groups = groups.filter(scorer_version_id__gt=position)
        rows = list(groups[: query.limit + 1])
        page = rows[: query.limit]
        next_cursor = self._next_cursor(query, scope, [str(page[-1])]) if len(rows) > query.limit else None
        return OfflinePage(
            count=count,
            next_cursor=next_cursor,
            results=list(
                self._summaries(
                    [_SummaryIdentity(experiment_id=experiment_id, version_id=version_id) for version_id in page]
                ).values()
            ),
        )

    def scorer_history(self, definition_id: UUID, query: OfflineReadQuery) -> OfflinePage[OfflineHistoryPoint]:
        if not self._definitions().filter(id=definition_id).exists():
            raise OfflineEvaluationNotFound
        self._validate_scorer_selection(query)
        if query.scorer_definition_id is not None and query.scorer_definition_id != definition_id:
            raise OfflineEvaluationNotFound
        if query.scorer_version_ids and self._versions().filter(
            definition_id=definition_id, id__in=query.scorer_version_ids
        ).count() != len(query.scorer_version_ids):
            raise OfflineEvaluationNotFound
        scope = f"history:{definition_id}"
        results = self._results(query).filter(
            scorer_definition_id=definition_id, item__experiment__in=self._filter_experiments(query, history=True)
        )
        groups = (
            results.order_by("-item__experiment__started_at", "item__experiment_id", "scorer_version_id")
            .values("item__experiment__started_at", "item__experiment_id", "scorer_version_id")
            .distinct()
        )
        count = groups.count()
        position = self._time_cursor(query, scope, history=True)
        if position is not None:
            groups = groups.filter(
                Q(item__experiment__started_at__lt=position.started_at)
                | Q(item__experiment__started_at=position.started_at, item__experiment_id__gt=position.experiment_id)
                | Q(
                    item__experiment__started_at=position.started_at,
                    item__experiment_id=position.experiment_id,
                    scorer_version_id__gt=position.version_id,
                )
            )
        rows = list(groups[: query.limit + 1])
        page = rows[: query.limit]
        identities = [
            _SummaryIdentity(experiment_id=row["item__experiment_id"], version_id=row["scorer_version_id"])
            for row in page
        ]
        summary_by_id = self._summaries(identities)
        experiments = {
            experiment.id: experiment
            for experiment in self._experiment_reads(
                list(self._experiments().filter(id__in={identity.experiment_id for identity in identities}))
            )
        }
        next_cursor = (
            self._next_cursor(
                query,
                scope,
                [
                    page[-1]["item__experiment__started_at"].isoformat(),
                    str(page[-1]["item__experiment_id"]),
                    str(page[-1]["scorer_version_id"]),
                ],
            )
            if len(rows) > query.limit
            else None
        )
        return OfflinePage(
            count=count,
            next_cursor=next_cursor,
            results=[
                OfflineHistoryPoint(experiment=experiments[identity.experiment_id], summary=summary_by_id[identity])
                for identity in identities
                if identity in summary_by_id
            ],
        )
