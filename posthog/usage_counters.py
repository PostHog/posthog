from collections.abc import Callable, Mapping
from datetime import datetime
from enum import StrEnum


class UsageCounter(StrEnum):
    CDP_INVOCATIONS = "teams_with_cdp_billable_invocations_in_period"
    FEATURE_FLAG_REQUESTS = "teams_with_decide_requests_count_in_period"
    FEATURE_FLAG_LOCAL_EVALUATION_REQUESTS = "teams_with_local_evaluation_requests_count_in_period"
    WORKFLOW_EMAILS = "teams_with_workflow_emails_sent_in_period"
    WORKFLOW_PUSH = "teams_with_workflow_push_sent_in_period"
    WORKFLOW_SMS = "teams_with_workflow_sms_sent_in_period"
    WORKFLOW_INVOCATIONS = "teams_with_workflow_billable_invocations_in_period"


UsageCounterQuery = Callable[[datetime, datetime], list[tuple[int, int]]]


class UsageCounterService:
    def __init__(self, queries: Mapping[UsageCounter, UsageCounterQuery]) -> None:
        self._queries = dict(queries)

    def get(self, counter: UsageCounter, begin: datetime, end: datetime) -> list[tuple[int, int]]:
        return self._queries[counter](begin, end)
