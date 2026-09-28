from dataclasses import replace

import pytest

from posthog.caching.insight_result import (
    InsightResult,
    InsightResultStatus,
    NothingInCacheResult,
    insight_result_status,
)

COMPUTED = InsightResult(result=[], last_refresh=None, cache_key="cache_key", is_cached=True, timezone="UTC")
NOT_COMPUTED = NothingInCacheResult(cache_key="cache_key")


@pytest.mark.parametrize(
    "result, expected",
    [
        (COMPUTED, InsightResultStatus.OK),
        (replace(COMPUTED, query_status={"id": "abc", "complete": True}), InsightResultStatus.OK),
        (replace(COMPUTED, query_status={"id": "abc", "complete": False}), InsightResultStatus.OK),
        (
            replace(COMPUTED, result=None, query_status={"id": "abc", "complete": False}),
            InsightResultStatus.QUERY_PENDING,
        ),
        (replace(COMPUTED, result=None, query_status={"id": "abc", "error": True}), InsightResultStatus.ERROR),
        (NOT_COMPUTED, InsightResultStatus.CACHE_MISS),
        (
            replace(NOT_COMPUTED, query_status={"id": "abc", "complete": False}),
            InsightResultStatus.QUERY_PENDING,
        ),
        (replace(NOT_COMPUTED, query_status={"id": "abc", "error": True}), InsightResultStatus.ERROR),
    ],
)
def test_insight_result_status(result: InsightResult, expected: InsightResultStatus) -> None:
    assert insight_result_status(result) == expected
