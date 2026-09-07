"""Executes one population operation, one bounded work unit at a time."""

from __future__ import annotations

import os
import socket
from dataclasses import replace

from django.db import InterfaceError, OperationalError
from django.utils import timezone

import grpc
import structlog
from celery.exceptions import SoftTimeLimitExceeded
from requests.exceptions import HTTPError, RequestException

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.services.flags_service import FlagVersionConflictError, PropertyMatchingVersionConflictError
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.errors import CH_TRANSIENT_ERRORS
from posthog.models.person.sql import PERSON_STATIC_COHORT_TABLE
from posthog.models.person.util import get_person_uuids_and_matched_distinct_ids
from posthog.models.team.team import Team
from posthog.personhog_client.caller_tag import personhog_caller_tag
from posthog.schema_enums import ProductKey
from posthog.storage.object_storage import ObjectStorageError

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.population import (
    CohortPopulationOperation,
    CohortPopulationPhase,
    CohortPopulationSource,
    CohortPopulationStatus,
)
from products.cohorts.backend.models.util import CohortErrorCode, count_cohort_members, parse_error_code
from products.cohorts.backend.population import operation as operation_lifecycle
from products.cohorts.backend.population.flag_pages import (
    COHORT_FLAG_GENERATION_EVAL_ERRORS_COUNTER,
    batch_evaluate_flag_page_with_retries,
)
from products.cohorts.backend.population.input_store import CohortPopulationInputMissing, append_chunk, read_chunk
from products.cohorts.backend.population.metrics import COHORT_POPULATION_OUTCOMES, COHORT_POPULATION_WORK_UNITS
from products.cohorts.backend.population.progress import PopulationProgress
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.team_feature_flags_config import (
    PropertyMatchingVersion,
    TeamFeatureFlagsConfig,
)

logger = structlog.get_logger(__name__)

SYNC_PAGE_SIZE = 10_000

# Pages of flag evaluation per materialization unit. The service evaluates a page under its own
# request timeout, so this stays well below its hard cap.
FLAG_EVALUATION_PAGE_SIZE = 2_000

MAX_WORK_UNITS_PER_TASK = 1


class PermanentPopulationError(Exception):
    """A failure no retry can fix. Carries the code a person sees."""

    def __init__(self, error_code: CohortErrorCode, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def run_operation(operation_id, *, worker: str | None = None, max_work_units: int = MAX_WORK_UNITS_PER_TASK) -> bool:
    """Drive an operation forward, up to `max_work_units`. Returns whether work is still left."""
    operation = operation_lifecycle.claim(operation_id, worker=worker or worker_identity())
    if operation is None:
        return False

    for _ in range(max_work_units):
        if not _run_one_unit(operation):
            return False

    # Out of budget with work left. Hand the claim back before the caller re-dispatches, or the
    # next worker would wait out this attempt's whole lease before it could pick the operation up.
    return operation_lifecycle.release(operation)


def dispatch_operation(operation_id) -> None:
    from posthog.tasks.calculate_cohort import run_cohort_population_operation

    try:
        run_cohort_population_operation.delay(str(operation_id))
    except Exception:
        logger.exception("cohort_population_publish_failed", operation_id=str(operation_id))


def _run_one_unit(operation: CohortPopulationOperation) -> bool:
    """Execute one unit for a claimed operation. Returns whether more work follows."""
    current = (
        CohortPopulationOperation.objects.unscoped()
        .filter(pk=operation.pk, claim_token=operation.claim_token, lease_expires_at__gt=timezone.now())
        .first()
    )
    if current is None:
        return False
    operation.abandon_requested_at = current.abandon_requested_at
    cohort = Cohort.objects.filter(pk=operation.cohort_id, team_id=operation.team_id).first()
    if cohort is None:
        operation_lifecycle.fail_permanently(operation, error_code=CohortErrorCode.VALIDATION_ERROR)
        return False

    try:
        if cohort.deleted or not cohort.is_static:
            raise PermanentPopulationError(CohortErrorCode.VALIDATION_ERROR, "Cohort is no longer available")
        if operation.abandon_requested_at is not None:
            has_more = _settle_abandonment(operation, cohort)
        else:
            has_more = _advance(operation, cohort)
    except PermanentPopulationError as err:
        _record_failure(operation, cohort, error_code=err.error_code, retryable=False, err=err)
        return False
    except Exception as err:
        _record_failure(operation, cohort, error_code=parse_error_code(err), retryable=_is_retryable(err), err=err)
        return False

    COHORT_POPULATION_WORK_UNITS.labels(source=operation.source, phase=operation.phase).inc()
    return has_more


def _is_retryable(error: Exception) -> bool:
    if isinstance(error, grpc.RpcError):
        return error.code() in {
            grpc.StatusCode.UNAVAILABLE,
            grpc.StatusCode.DEADLINE_EXCEEDED,
            grpc.StatusCode.ABORTED,
            grpc.StatusCode.UNKNOWN,
        }
    if isinstance(error, HTTPError) and error.response is not None:
        # The flags service answers a request it will never accept with a 4xx. Only a throttled or
        # timed-out request is worth sending again.
        return error.response.status_code in (408, 429) or error.response.status_code >= 500
    return isinstance(
        error,
        (
            *CH_TRANSIENT_ERRORS,
            OperationalError,
            InterfaceError,
            ObjectStorageError,
            RequestException,
            ConnectionError,
            TimeoutError,
            SoftTimeLimitExceeded,
        ),
    )


def _advance(operation: CohortPopulationOperation, cohort: Cohort) -> bool:
    match operation.phase:
        case CohortPopulationPhase.MATERIALIZING_SOURCE:
            return _materialize_source(operation, cohort)
        case CohortPopulationPhase.WRITING_MEMBERSHIP:
            return _write_next_input_chunk(operation, cohort)
        case CohortPopulationPhase.SYNCHRONIZING:
            return _synchronize_next_page(operation, cohort)
        case CohortPopulationPhase.FINALIZING:
            return _finalize(operation, cohort)
        case _:
            raise PermanentPopulationError(
                CohortErrorCode.UNKNOWN, f"operation {operation.pk} is in unrunnable phase {operation.phase}"
            )


def _materialize_source(operation: CohortPopulationOperation, cohort: Cohort) -> bool:
    match operation.source:
        case CohortPopulationSource.QUERY | CohortPopulationSource.FILTERS:
            return _materialize_clickhouse_source(operation, cohort)
        case CohortPopulationSource.FEATURE_FLAG:
            return _evaluate_next_flag_page(operation, cohort)
        case _:
            raise PermanentPopulationError(
                CohortErrorCode.UNKNOWN, f"source {operation.source} has nothing to materialize"
            )


def _materialize_clickhouse_source(operation: CohortPopulationOperation, cohort: Cohort) -> bool:
    """Evaluate the cohort's saved query or criteria into ClickHouse, once per operation."""
    from products.cohorts.backend.models.util import (
        insert_cohort_filter_actors_into_ch,
        insert_cohort_query_actors_into_ch,
    )

    progress = PopulationProgress.from_json(operation.progress)
    if not progress.source_materialized:
        team = Team.objects.get(pk=operation.team_id)
        cohort.query = operation.source_config.get("query", cohort.query)
        cohort.filters = operation.source_config.get("filters", cohort.filters)
        try:
            if operation.source == CohortPopulationSource.QUERY:
                insert_cohort_query_actors_into_ch(cohort, team=team, execution_timeout=1200)
            else:
                insert_cohort_filter_actors_into_ch(cohort, team=team, execution_timeout=1200)
        except ExposedHogQLError as err:
            raise PermanentPopulationError(CohortErrorCode.VALIDATION_ERROR, str(err)) from err

    return operation_lifecycle.checkpoint(
        operation,
        progress=replace(progress, source_materialized=True),
        phase=CohortPopulationPhase.SYNCHRONIZING,
    )


def _evaluate_next_flag_page(operation: CohortPopulationOperation, cohort: Cohort) -> bool:
    """Fetch one page of flag matches and persist it before any membership is written."""
    progress = PopulationProgress.from_json(operation.progress)
    flag_key = (operation.input_manifest or {}).get("flag_key")
    if not flag_key:
        raise PermanentPopulationError(CohortErrorCode.UNKNOWN, "feature flag operation has no flag key")

    project_id = Team.objects.only("project_id").get(pk=operation.team_id).project_id
    feature_flag = FeatureFlag.objects.filter(team__project_id=project_id, key=flag_key).first()
    if feature_flag is None or not feature_flag.active or feature_flag.aggregation_group_type_index is not None:
        if progress.pinned_flag_version is not None:
            raise PermanentPopulationError(CohortErrorCode.FLAG_CHANGED, "Feature flag is no longer evaluable")
        return operation_lifecycle.checkpoint(operation, progress=progress, phase=CohortPopulationPhase.FINALIZING)

    if progress.pinned_flag_version is None:
        progress = replace(
            progress,
            pinned_flag_version=feature_flag.version or 0,
            pinned_property_matching_version=_property_matching_version(operation.team_id),
        )
        return operation_lifecycle.checkpoint(operation, progress=progress)

    try:
        page = batch_evaluate_flag_page_with_retries(
            team_id=operation.team_id,
            project_id=project_id,
            flag_key=feature_flag.key,
            expected_version=progress.pinned_flag_version or 0,
            expected_property_matching_version=progress.pinned_property_matching_version or 0,
            cursor=progress.flag_cursor or 0,
            limit=FLAG_EVALUATION_PAGE_SIZE,
        )
    except (FlagVersionConflictError, PropertyMatchingVersionConflictError) as err:
        raise PermanentPopulationError(CohortErrorCode.FLAG_CHANGED, str(err)) from err

    errors_count = page.get("errors_count") or 0
    if errors_count:
        COHORT_FLAG_GENERATION_EVAL_ERRORS_COUNTER.inc(errors_count)
        logger.warning(
            "cohort_from_feature_flag_eval_errors",
            cohort_id=cohort.pk,
            team_id=operation.team_id,
            flag_key=feature_flag.key,
            cursor=progress.flag_cursor,
            errors_count=errors_count,
        )

    manifest = append_chunk(operation.input_manifest or {}, page["matched_person_uuids"])
    next_cursor = page["next_cursor"]
    if next_cursor is not None and next_cursor <= (progress.flag_cursor or 0):
        raise PermanentPopulationError(
            CohortErrorCode.UNKNOWN,
            f"batch flag evaluation cursor did not advance (got {next_cursor} after {progress.flag_cursor})",
        )

    return operation_lifecycle.checkpoint(
        operation,
        progress=replace(progress, flag_cursor=next_cursor),
        phase=CohortPopulationPhase.WRITING_MEMBERSHIP,
        input_manifest=manifest,
    )


def _property_matching_version(team_id: int) -> int:
    return (
        TeamFeatureFlagsConfig.objects.filter(team_id=team_id)
        .values_list("property_matching_version", flat=True)
        .first()
        or PropertyMatchingVersion.LEGACY
    )


def _write_next_input_chunk(operation: CohortPopulationOperation, cohort: Cohort) -> bool:
    """Resolve one retained chunk and write it to both stores, then checkpoint."""
    manifest = operation.input_manifest
    progress = PopulationProgress.from_json(operation.progress)

    if manifest is None:
        raise PermanentPopulationError(CohortErrorCode.INPUT_UNAVAILABLE, "Population input is missing")
    if progress.chunk_index >= manifest["chunks"]:
        phase = (
            CohortPopulationPhase.MATERIALIZING_SOURCE
            if operation.source == CohortPopulationSource.FEATURE_FLAG and progress.flag_cursor is not None
            else CohortPopulationPhase.FINALIZING
        )
        return operation_lifecycle.checkpoint(operation, progress=progress, phase=phase)

    try:
        chunk = read_chunk(manifest, progress.chunk_index)
    except CohortPopulationInputMissing as err:
        raise PermanentPopulationError(CohortErrorCode.INPUT_UNAVAILABLE, str(err)) from err

    matched = _resolve_and_insert(cohort, chunk, id_type=manifest["id_type"], team_id=operation.team_id)

    return operation_lifecycle.checkpoint(
        operation,
        progress=replace(
            progress,
            chunk_index=progress.chunk_index + 1,
            matched=progress.matched + matched,
            unmatched=progress.unmatched + (len(chunk) - matched),
        ),
    )


def _resolve_and_insert(cohort: Cohort, chunk: list[str], *, id_type: str, team_id: int) -> int:
    """Write one chunk of identifiers into both stores. Returns how many identifiers matched a person."""
    if not chunk:
        return 0

    match id_type:
        case "person_id":
            matched_uuids = cohort._insert_batch_via_personhog(chunk, True, team_id=team_id)
            return len(matched_uuids)
        case "distinct_id":
            with personhog_caller_tag("cohorts/population-resolve"):
                uuids, matched_distinct_ids = get_person_uuids_and_matched_distinct_ids(team_id, chunk)
            cohort._insert_batch_via_personhog(uuids, True, team_id=team_id)
            return len(matched_distinct_ids)
        case "email":
            uuids, matched_emails = cohort._get_uuids_for_emails_batch_ch(chunk, team_id)
            cohort._insert_batch_via_personhog(uuids, True, team_id=team_id)
            return len(matched_emails)
        case _:
            raise PermanentPopulationError(CohortErrorCode.VALIDATION_ERROR, f"unsupported id type {id_type}")


def _synchronize_next_page(operation: CohortPopulationOperation, cohort: Cohort) -> bool:
    """Copy one page of the materialized ClickHouse membership into Postgres."""
    progress = PopulationProgress.from_json(operation.progress)

    tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
    # nosemgrep: clickhouse-fstring-param-audit - table name from constant, values parameterized
    rows = sync_execute(
        f"SELECT DISTINCT person_id FROM {PERSON_STATIC_COHORT_TABLE} "
        "WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s AND person_id > %(cursor)s "
        "ORDER BY person_id LIMIT %(limit)s",
        {
            "team_id": operation.team_id,
            "cohort_id": cohort.pk,
            "cursor": progress.sync_cursor,
            "limit": SYNC_PAGE_SIZE,
        },
    )

    if not rows:
        return operation_lifecycle.checkpoint(
            operation,
            progress=replace(progress, sync_complete=True),
            phase=CohortPopulationPhase.FINALIZING,
        )

    uuids = [str(row[0]) for row in rows]
    cohort._insert_batch_via_personhog(uuids, False, team_id=operation.team_id)

    return operation_lifecycle.checkpoint(
        operation,
        progress=replace(progress, sync_cursor=uuids[-1]),
    )


def _finalize(operation: CohortPopulationOperation, cohort: Cohort) -> bool:
    count = count_cohort_members(team_id=operation.team_id, cohort_id=cohort.pk, consistency="strong")
    if operation.abandon_requested_at is not None:
        finished = operation_lifecycle.abandon(operation, count=count)
        outcome = "abandoned"
    else:
        finished = operation_lifecycle.complete(operation, count=count)
        outcome = "completed"
    if finished:
        COHORT_POPULATION_OUTCOMES.labels(source=operation.source, outcome=outcome).inc()
        return False
    # An abandon request can arrive during the count. Yield so its synchronization runs next.
    return True


def _settle_abandonment(operation: CohortPopulationOperation, cohort: Cohort) -> bool:
    progress = PopulationProgress.from_json(operation.progress)
    if not progress.abandon_sync_started:
        return operation_lifecycle.checkpoint(
            operation,
            progress=replace(
                progress, abandon_sync_started=True, sync_complete=False, sync_cursor=PopulationProgress().sync_cursor
            ),
            phase=CohortPopulationPhase.SYNCHRONIZING,
        )
    if not progress.sync_complete:
        return _synchronize_next_page(operation, cohort)
    return _finalize(operation, cohort)


def _record_failure(
    operation: CohortPopulationOperation,
    cohort: Cohort,
    *,
    error_code: CohortErrorCode,
    retryable: bool,
    err: Exception,
) -> None:
    """Release the attempt, and release the cohort only once nothing else will retry."""
    logger.warning(
        "cohort_population_work_unit_failed",
        operation_id=str(operation.pk),
        cohort_id=cohort.pk,
        team_id=operation.team_id,
        phase=operation.phase,
        source=operation.source,
        error_code=error_code.value,
        error_type=type(err).__name__,
    )

    try:
        recorded = (
            operation_lifecycle.schedule_retry(operation, error_code=error_code)
            if retryable
            else operation_lifecycle.fail_permanently(operation, error_code=error_code)
        )
    except Exception:
        # Leave the lease recoverable when bookkeeping fails, preserving the original error above.
        logger.exception("cohort_population_failure_bookkeeping_failed", operation_id=str(operation.pk))
        raise err
    if recorded:
        outcome = "failed" if operation.status == CohortPopulationStatus.FAILED else "retry_scheduled"
        COHORT_POPULATION_OUTCOMES.labels(source=operation.source, outcome=outcome).inc()
