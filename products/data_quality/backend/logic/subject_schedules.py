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
from ..facade.enums import ScheduleInterval, SubjectType, SuiteRunTrigger

SCHEDULE_TYPES: dict[SubjectType, str] = {
    SubjectType.METRIC: "data-quality-metric",
    SubjectType.POSTHOG_TABLE: "data-quality-posthog-table",
}
SCHEDULE_TYPE_SUBJECTS = {schedule_type: kind for kind, schedule_type in SCHEDULE_TYPES.items()}


def runs_on_a_schedule(subject_type: SubjectType) -> bool:
    return subject_type in SCHEDULE_TYPES


CATCHUP_WINDOW = timedelta(minutes=15)
INTERVALS = {
    ScheduleInterval.ONE_HOUR: timedelta(hours=1),
    ScheduleInterval.SIX_HOURS: timedelta(hours=6),
    ScheduleInterval.TWELVE_HOURS: timedelta(hours=12),
    ScheduleInterval.DAILY: timedelta(days=1),
    ScheduleInterval.WEEKLY: timedelta(days=7),
}


@frozen
class SubjectScheduleKey:
    """Which subject a Temporal schedule runs the checks of."""

    team_id: int
    subject_type: SubjectType
    subject_uuid: UUID

    @property
    def schedule_type(self) -> str:
        schedule_type = SCHEDULE_TYPES.get(self.subject_type)
        if schedule_type is None:
            raise ValueError(f"A {self.subject_type} has no recurring check schedule")
        return schedule_type

    @property
    def id(self) -> UUID:
        return uuid5(NAMESPACE_URL, self.temporal_id)

    @property
    def temporal_id(self) -> str:
        return f"{self.schedule_type}:{self.team_id}:{self.subject_uuid}"

    @classmethod
    def parse(cls, schedule_id: str) -> "SubjectScheduleKey":
        schedule_type, team_id, subject_uuid = schedule_id.split(":")
        subject_type = SCHEDULE_TYPE_SUBJECTS.get(schedule_type)
        if subject_type is None:
            raise ValueError("Unrecognized check schedule identifier")
        return cls(team_id=int(team_id), subject_type=subject_type, subject_uuid=UUID(subject_uuid))


def suite_inputs(key: SubjectScheduleKey) -> RunCheckSuiteInputs:
    """What this schedule hands the workflow, with its subject in the selector that kind uses."""
    if key.subject_type is SubjectType.METRIC:
        return RunCheckSuiteInputs(
            team_id=key.team_id,
            trigger=SuiteRunTrigger.SCHEDULED,
            metric_ids=[str(key.subject_uuid)],
            schedule_id=key.temporal_id,
        )
    if key.subject_type is SubjectType.POSTHOG_TABLE:
        return RunCheckSuiteInputs(
            team_id=key.team_id,
            trigger=SuiteRunTrigger.SCHEDULED,
            posthog_table_ids=[str(key.subject_uuid)],
            schedule_id=key.temporal_id,
        )
    raise ValueError(f"A {key.subject_type} has no recurring check schedule")


def selected_subject_ids(inputs: RunCheckSuiteInputs, subject_type: SubjectType) -> list[str]:
    """The subjects these inputs name, read out of the selector that kind uses."""
    if subject_type is SubjectType.METRIC:
        return inputs.metric_ids
    if subject_type is SubjectType.POSTHOG_TABLE:
        return inputs.posthog_table_ids
    raise ValueError(f"A {subject_type} has no recurring check schedule")


def interval_from_label(label: str) -> timedelta:
    return INTERVALS[ScheduleInterval(label)]


def label_from_interval(interval: timedelta) -> ScheduleInterval:
    for label, duration in INTERVALS.items():
        if interval == duration:
            return label
    raise ValueError("Unsupported check interval")


class SubjectSchedules:
    def __init__(self, client: Client) -> None:
        self.client = client

    @staticmethod
    def spec(key: SubjectScheduleKey, interval: str) -> ScheduleSpec:
        duration = interval_from_label(interval)
        offset = timedelta(seconds=key.id.int % int(duration.total_seconds()))
        return ScheduleSpec(intervals=[ScheduleIntervalSpec(every=duration, offset=offset)])

    @classmethod
    def build(cls, key: SubjectScheduleKey, interval: str = ScheduleInterval.DAILY) -> Schedule:
        return Schedule(
            action=ScheduleActionStartWorkflow(
                CHECK_SUITE_WORKFLOW_NAME,
                suite_inputs(key),
                id=key.temporal_id,
                task_queue=settings.DATA_MODELING_TASK_QUEUE,
                execution_timeout=timedelta(hours=1),
            ),
            spec=cls.spec(key, interval),
            policy=SchedulePolicy(
                overlap=ScheduleOverlapPolicy.SKIP, catchup_window=CATCHUP_WINDOW, pause_on_failure=False
            ),
        )

    async def ensure(self, key: SubjectScheduleKey) -> None:
        try:
            await a_create_schedule(
                self.client,
                id=key.temporal_id,
                schedule=self.build(key),
                trigger_immediately=True,
                search_attributes=TypedSearchAttributes(
                    [
                        SearchAttributePair(POSTHOG_TEAM_ID_KEY, key.team_id),
                        SearchAttributePair(POSTHOG_SCHEDULE_TYPE_KEY, key.schedule_type),
                    ]
                ),
            )
        except ScheduleAlreadyRunningError:
            return

    async def describe(self, key: SubjectScheduleKey) -> ScheduleDescription | None:
        try:
            return await a_describe_schedule(self.client, key.temporal_id)
        except RPCError as error:
            if error.status == RPCStatusCode.NOT_FOUND:
                return None
            raise

    async def update(
        self, key: SubjectScheduleKey, *, interval: str | None = None, enabled: bool | None = None
    ) -> None:
        spec = self.spec(key, interval) if interval is not None else None

        def updater(inputs: ScheduleUpdateInput) -> ScheduleUpdate:
            schedule = deepcopy(inputs.description.schedule)
            if spec is not None:
                schedule.spec.intervals = spec.intervals
            if enabled is not None:
                schedule.state.paused = not enabled
            return ScheduleUpdate(schedule=schedule)

        await self.client.get_schedule_handle(key.temporal_id).update(updater)
