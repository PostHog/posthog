from copy import deepcopy
from datetime import timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleDescription,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleUpdate,
    ScheduleUpdateInput,
)
from temporalio.common import SearchAttributePair, TypedSearchAttributes
from temporalio.service import RPCError, RPCStatusCode

from posthog.dataclasses import frozen
from posthog.temporal.common.schedule import a_create_schedule, a_describe_schedule
from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_TYPE_KEY, POSTHOG_TEAM_ID_KEY

from ..facade.contracts import CHECK_SUITE_WORKFLOW_NAME, RunCheckSuiteInputs
from ..facade.enums import ScheduleInterval, SuiteRunTrigger

SCHEDULE_TYPE = "data-quality-metric"
SCHEDULE_PREFIX = f"{SCHEDULE_TYPE}:"
CATCHUP_WINDOW = timedelta(minutes=15)
INTERVALS = {
    ScheduleInterval.ONE_HOUR: timedelta(hours=1),
    ScheduleInterval.SIX_HOURS: timedelta(hours=6),
    ScheduleInterval.TWELVE_HOURS: timedelta(hours=12),
    ScheduleInterval.DAILY: timedelta(days=1),
    ScheduleInterval.WEEKLY: timedelta(days=7),
}


@frozen
class MetricScheduleKey:
    team_id: int
    metric_id: UUID

    @property
    def id(self) -> UUID:
        return uuid5(NAMESPACE_URL, f"{SCHEDULE_PREFIX}{self.team_id}:{self.metric_id}")

    @property
    def temporal_id(self) -> str:
        return f"{SCHEDULE_PREFIX}{self.team_id}:{self.metric_id}"

    @classmethod
    def parse(cls, schedule_id: str) -> "MetricScheduleKey":
        prefix, team_id, metric_id = schedule_id.split(":")
        if prefix != SCHEDULE_TYPE:
            raise ValueError("Unrecognized metric schedule identifier")
        return cls(team_id=int(team_id), metric_id=UUID(metric_id))


def interval_from_label(label: str) -> timedelta:
    return INTERVALS[ScheduleInterval(label)]


def label_from_interval(interval: timedelta) -> ScheduleInterval:
    for label, duration in INTERVALS.items():
        if interval == duration:
            return label
    raise ValueError("Unsupported metric check interval")


class MetricSchedules:
    def __init__(self, client: Client) -> None:
        self.client = client

    @staticmethod
    def spec(key: MetricScheduleKey, interval: str) -> ScheduleSpec:
        duration = interval_from_label(interval)
        offset = timedelta(seconds=key.id.int % int(duration.total_seconds()))
        return ScheduleSpec(intervals=[ScheduleIntervalSpec(every=duration, offset=offset)])

    @classmethod
    def build(cls, key: MetricScheduleKey, interval: str = ScheduleInterval.DAILY) -> Schedule:
        return Schedule(
            action=ScheduleActionStartWorkflow(
                CHECK_SUITE_WORKFLOW_NAME,
                RunCheckSuiteInputs(
                    team_id=key.team_id,
                    trigger=SuiteRunTrigger.SCHEDULED,
                    metric_ids=[str(key.metric_id)],
                    schedule_id=key.temporal_id,
                ),
                id=key.temporal_id,
                task_queue=settings.DATA_MODELING_TASK_QUEUE,
                execution_timeout=timedelta(hours=1),
            ),
            spec=cls.spec(key, interval),
            policy=SchedulePolicy(
                overlap=ScheduleOverlapPolicy.SKIP, catchup_window=CATCHUP_WINDOW, pause_on_failure=False
            ),
        )

    async def ensure(self, key: MetricScheduleKey) -> None:
        try:
            await a_create_schedule(
                self.client,
                id=key.temporal_id,
                schedule=self.build(key),
                trigger_immediately=True,
                search_attributes=TypedSearchAttributes(
                    [
                        SearchAttributePair(POSTHOG_TEAM_ID_KEY, key.team_id),
                        SearchAttributePair(POSTHOG_SCHEDULE_TYPE_KEY, SCHEDULE_TYPE),
                    ]
                ),
            )
        except ScheduleAlreadyRunningError:
            return

    async def describe(self, key: MetricScheduleKey) -> ScheduleDescription | None:
        try:
            return await a_describe_schedule(self.client, key.temporal_id)
        except RPCError as error:
            if error.status == RPCStatusCode.NOT_FOUND:
                return None
            raise

    async def update(self, key: MetricScheduleKey, *, interval: str | None = None, enabled: bool | None = None) -> None:
        spec = self.spec(key, interval) if interval is not None else None

        def updater(inputs: ScheduleUpdateInput) -> ScheduleUpdate:
            schedule = deepcopy(inputs.description.schedule)
            if spec is not None:
                schedule.spec.intervals = spec.intervals
            if enabled is not None:
                schedule.state.paused = not enabled
            return ScheduleUpdate(schedule=schedule)

        await self.client.get_schedule_handle(key.temporal_id).update(updater)
