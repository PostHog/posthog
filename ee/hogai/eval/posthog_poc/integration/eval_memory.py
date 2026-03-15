from __future__ import annotations

import pytest

from ..runner import run_suite
from ..suites.memory import MEMORY_CASES, build_memory_suite


@pytest.mark.django_db
async def eval_memory_posthog_poc(call_memory_collector, posthog_eval_client) -> None:
    suite = build_memory_suite(call_memory_collector)
    results = await run_suite(suite, posthog_eval_client)

    assert len(results) == len(MEMORY_CASES)
    assert all(result["status"] == "ok" for result in results)
