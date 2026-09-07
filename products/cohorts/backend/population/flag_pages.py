"""One page of feature-flag evaluation, with the transport retries a page is allowed."""

from __future__ import annotations

import time
from typing import Any

import requests
import structlog
from prometheus_client import Counter, Histogram

from posthog.api.services.flags_service import (
    FlagVersionConflictError,
    PropertyMatchingVersionConflictError,
    batch_evaluate_flag_for_team,
)

logger = structlog.get_logger(__name__)

# Number of attempts per page when calling the batch evaluation endpoint, including the
# first try. Only transient failures (connection errors, timeouts, 5xx) are retried.
BATCH_FLAG_EVALUATION_PAGE_ATTEMPTS = 3
BATCH_FLAG_EVALUATION_RETRY_BACKOFF_SECONDS = 2.0

COHORT_FLAG_GENERATION_COMPLETED_COUNTER = Counter(
    "cohort_flag_generation_completed_total",
    "Cohort generations from a feature flag that finished, by outcome",
    ["outcome"],  # "success" or a CohortErrorCode value ("flag_changed", "unknown")
)

COHORT_FLAG_GENERATION_DURATION_SECONDS = Histogram(
    "cohort_flag_generation_duration_seconds",
    "Duration of cohort generation from a feature flag in seconds",
    ["outcome"],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600, 7200, 14400],
)

COHORT_FLAG_GENERATION_PAGE_RETRIES_COUNTER = Counter(
    "cohort_flag_generation_page_retries_total",
    "Transient batch flag evaluation page failures that were retried against the flags service",
)

COHORT_FLAG_GENERATION_EVAL_ERRORS_COUNTER = Counter(
    "cohort_flag_generation_eval_errors_total",
    "Per-person evaluation errors reported by the flags service during cohort generation",
)


def batch_evaluate_flag_page_with_retries(
    *,
    team_id: int,
    project_id: int,
    flag_key: str,
    expected_version: int,
    expected_property_matching_version: int,
    cursor: int,
    limit: int,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(BATCH_FLAG_EVALUATION_PAGE_ATTEMPTS):
        if attempt > 0:
            COHORT_FLAG_GENERATION_PAGE_RETRIES_COUNTER.inc()
            time.sleep(BATCH_FLAG_EVALUATION_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
        try:
            return batch_evaluate_flag_for_team(
                team_id=team_id,
                project_id=project_id,
                flag_key=flag_key,
                expected_version=expected_version,
                expected_property_matching_version=expected_property_matching_version,
                cursor=cursor,
                limit=limit,
            )
        except (FlagVersionConflictError, PropertyMatchingVersionConflictError):
            # Permanent: the pinned evaluation inputs changed; retrying the same page cannot help.
            raise
        except requests.RequestException as err:
            if (
                isinstance(err, requests.HTTPError)
                and err.response is not None
                and 400 <= err.response.status_code < 500
            ):
                # Permanent client errors (bad request, missing flag, auth misconfiguration).
                raise
            last_error = err
            logger.warning(
                "cohort_from_feature_flag_page_retry",
                team_id=team_id,
                flag_key=flag_key,
                cursor=cursor,
                attempt=attempt + 1,
                error=str(err),
            )
    assert last_error is not None
    raise last_error
