from __future__ import annotations

import pytest

from ..runner import run_suite
from ..suites.ticket_summary import TICKET_SUMMARY_CASES, build_ticket_summary_suite


@pytest.mark.django_db
async def eval_ticket_summary_posthog_poc(call_ticket_summary_summarizer, posthog_eval_client) -> None:
    suite = build_ticket_summary_suite(call_ticket_summary_summarizer)
    results = await run_suite(suite, posthog_eval_client)

    assert len(results) == len(TICKET_SUMMARY_CASES)
    assert all(result["status"] == "ok" for result in results)
