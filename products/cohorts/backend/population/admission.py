"""How a static cohort's population run is started."""

from __future__ import annotations

from django.db import transaction

from posthog.models.utils import uuid7

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.population import CohortPopulationOperation, CohortPopulationSource
from products.cohorts.backend.population import operation as operation_lifecycle
from products.cohorts.backend.population.input_store import delete_input, empty_manifest, write_input
from products.cohorts.backend.population.runner import dispatch_operation
from products.cohorts.backend.realtime_teams import is_durable_cohort_population_team

__all__ = [
    "admit_feature_flag_population",
    "admit_list_population",
    "admit_query_or_filters_population",
    "durable_population_enabled_for",
]


def durable_population_enabled_for(team_id: int) -> bool:
    return is_durable_cohort_population_team(team_id)


def admit_list_population(
    *,
    cohort: Cohort,
    team_id: int,
    identifiers: list[str],
    id_type: str,
    created_by_id: int | None = None,
    dispatch: bool = True,
) -> CohortPopulationOperation:
    """Persist the identifiers, then admit the run that will write them."""
    operation_id = uuid7()
    manifest = write_input(team_id=team_id, operation_id=operation_id, identifiers=identifiers, id_type=id_type)

    try:
        operation = operation_lifecycle.admit(
            operation_id=operation_id,
            cohort=cohort,
            team_id=team_id,
            source=CohortPopulationSource.LIST,
            input_manifest=manifest,
            created_by_id=created_by_id,
        )
    except Exception:
        try:
            delete_input(manifest)
        except Exception:
            pass
        raise
    _dispatch_if_asked(operation, dispatch)
    return operation


def admit_query_or_filters_population(
    *,
    cohort: Cohort,
    team_id: int,
    source: CohortPopulationSource,
    created_by_id: int | None = None,
    dispatch: bool = True,
) -> CohortPopulationOperation:
    """Admit a run whose members come from the cohort's own saved query or criteria."""
    operation = operation_lifecycle.admit(
        operation_id=uuid7(),
        cohort=cohort,
        team_id=team_id,
        source=source,
        created_by_id=created_by_id,
        source_config={"query": cohort.query, "filters": cohort.filters},
    )
    _dispatch_if_asked(operation, dispatch)
    return operation


def admit_feature_flag_population(
    *,
    cohort: Cohort,
    team_id: int,
    flag_key: str,
    created_by_id: int | None = None,
    dispatch: bool = True,
) -> CohortPopulationOperation:
    """Admit a run that pages a feature flag's matches, persisting each page before it is written."""
    operation_id = uuid7()
    manifest = empty_manifest(team_id=team_id, operation_id=operation_id, id_type="person_id")
    manifest["flag_key"] = flag_key

    operation = operation_lifecycle.admit(
        operation_id=operation_id,
        cohort=cohort,
        team_id=team_id,
        source=CohortPopulationSource.FEATURE_FLAG,
        input_manifest=manifest,
        created_by_id=created_by_id,
    )
    _dispatch_if_asked(operation, dispatch)
    return operation


def _dispatch_if_asked(operation: CohortPopulationOperation, dispatch: bool) -> None:
    if not dispatch:
        return
    # On commit, so a rolled-back request never leaves a worker chasing an operation that does not
    # exist. The periodic sweep covers the opposite case, a commit whose publish never landed.
    transaction.on_commit(lambda: dispatch_operation(operation.pk))
