import uuid
import logging
import datetime as dt
from dataclasses import dataclass

import pytest

from asgiref.sync import sync_to_async
from prometheus_client import REGISTRY
from pydantic import BaseModel
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import ExecuteActivityInput, UnsandboxedWorkflowRunner, Worker

from posthog.models import Organization, Team, organization_admission
from posthog.models.organization_admission import OrganizationAdmission
from posthog.temporal.common.interceptor import is_task_queue_supported
from posthog.temporal.common.organization_admission import OrganizationAdmissionInterceptor, _tenant_of
from posthog.temporal.common.worker import interceptor_classes
from posthog.test.waiting import wait_until

OUTCOMES = ("admitted", "would_skip", "unresolved", "unavailable", "error")


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@dataclass(frozen=True)
class ProbeInput:
    value: str
    team_id: int | None = None
    organization_id: str | None = None


@activity.defn
async def tenant_probe_activity(inputs: ProbeInput) -> str:
    return f"ran {inputs.value}"


@activity.defn
async def bare_probe_activity(value: str) -> str:
    return f"ran {value}"


@workflow.defn(name="organization-admission-probe")
class AdmissionProbeWorkflow:
    @workflow.run
    async def run(self, inputs: ProbeInput) -> list[str]:
        timeout = dt.timedelta(seconds=10)
        return [
            await workflow.execute_activity(tenant_probe_activity, inputs, start_to_close_timeout=timeout),
            await workflow.execute_activity(bare_probe_activity, inputs.value, start_to_close_timeout=timeout),
        ]


def _checks(task_queue: str, activity_type: str) -> dict[str, float]:
    counts = {
        outcome: REGISTRY.get_sample_value(
            "temporal_organization_admission_checks_total",
            {"task_queue": task_queue, "activity_type": activity_type, "outcome": outcome},
        )
        for outcome in OUTCOMES
    }
    return {outcome: count for outcome, count in counts.items() if count}


async def _run_probe(client: Client, inputs: ProbeInput) -> tuple[list[str], dict[str, float], dict[str, float]]:
    task_queue = f"admission-{uuid.uuid4()}"
    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[AdmissionProbeWorkflow],
        activities=[tenant_probe_activity, bare_probe_activity],
        interceptors=[cls() for cls in interceptor_classes() if is_task_queue_supported(task_queue, cls)],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        result = await client.execute_workflow(
            AdmissionProbeWorkflow.run,
            inputs,
            id=str(uuid.uuid4()),
            task_queue=task_queue,
            execution_timeout=dt.timedelta(seconds=30),
        )
    return result, _checks(task_queue, "tenant_probe_activity"), _checks(task_queue, "bare_probe_activity")


async def _team_in_organization(is_active: bool | None) -> Team:
    organization = await sync_to_async(Organization.objects.create)(name="Admission probe org", is_active=is_active)
    return await sync_to_async(Team.objects.create)(organization=organization, name="Admission probe team")


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> FakeClock:
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    clock = FakeClock()
    monkeypatch.setattr(organization_admission, "ORGANIZATION_ADMISSION", OrganizationAdmission(clock=clock))
    return clock


def _refreshes(outcome: str) -> float:
    return REGISTRY.get_sample_value("temporal_organization_admission_refreshes_total", {"outcome": outcome}) or 0.0


async def _load_snapshot() -> None:
    await sync_to_async(organization_admission.ORGANIZATION_ADMISSION.refresh_if_stale)()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "is_active,by_organization,expected",
    [
        (True, False, "admitted"),
        (None, False, "admitted"),
        (False, False, "would_skip"),
        (False, True, "would_skip"),
        (True, True, "admitted"),
    ],
)
async def test_shadow_counts_each_activity_and_leaves_its_result(
    temporal_client: Client, settings, clock: FakeClock, is_active: bool | None, by_organization: bool, expected: str
) -> None:
    settings.TEMPORAL_ORGANIZATION_ADMISSION_MODE = "shadow"
    team = await _team_in_organization(is_active)
    await _load_snapshot()
    inputs = (
        ProbeInput(value="x", organization_id=str(team.organization_id))
        if by_organization
        else ProbeInput(value="x", team_id=team.id)
    )

    result, tenant_checks, bare_checks = await _run_probe(temporal_client, inputs)

    assert result == ["ran x", "ran x"]
    assert tenant_checks == {expected: 1}
    assert bare_checks == {"unresolved": 1}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_shadow_on_a_cold_worker_counts_unavailable_and_loads_in_the_background(
    temporal_client: Client, settings, clock: FakeClock
) -> None:
    settings.TEMPORAL_ORGANIZATION_ADMISSION_MODE = "shadow"
    team = await _team_in_organization(is_active=False)
    inputs = ProbeInput(value="x", team_id=team.id)

    loaded_before = _refreshes("succeeded")
    result, cold, _ = await _run_probe(temporal_client, inputs)
    await sync_to_async(wait_until)(lambda: _refreshes("succeeded") == loaded_before + 1)
    _, loaded, _ = await _run_probe(temporal_client, inputs)

    assert result == ["ran x", "ran x"]
    assert cold == {"unavailable": 1}
    assert loaded == {"would_skip": 1}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_shadow_counts_against_the_cached_set_while_it_refreshes(
    temporal_client: Client, settings, clock: FakeClock
) -> None:
    settings.TEMPORAL_ORGANIZATION_ADMISSION_MODE = "shadow"
    team = await _team_in_organization(is_active=True)
    await _load_snapshot()
    inputs = ProbeInput(value="x", team_id=team.id)

    await sync_to_async(Organization.objects.filter(id=team.organization_id).update)(is_active=False)
    clock.now += 30
    loaded_before = _refreshes("succeeded")
    _, while_refreshing, _ = await _run_probe(temporal_client, inputs)
    await sync_to_async(wait_until)(lambda: _refreshes("succeeded") == loaded_before + 1)
    _, after_refresh, _ = await _run_probe(temporal_client, inputs)

    assert while_refreshing == {"admitted": 1}
    assert after_refresh == {"would_skip": 1}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("tenant", [{"team_id": None}, {"team_id": 0}, {"organization_id": "not-a-uuid"}])
async def test_shadow_counts_a_tenant_that_does_not_resolve(
    temporal_client: Client, settings, clock: FakeClock, tenant: dict
) -> None:
    settings.TEMPORAL_ORGANIZATION_ADMISSION_MODE = "shadow"

    result, tenant_checks, _ = await _run_probe(temporal_client, ProbeInput(value="x", **tenant))

    assert result == ["ran x", "ran x"]
    assert tenant_checks == {"unresolved": 1}


@pytest.mark.asyncio
async def test_shadow_runs_the_activity_when_the_lookup_fails(
    temporal_client: Client, settings, clock: FakeClock
) -> None:
    settings.TEMPORAL_ORGANIZATION_ADMISSION_MODE = "shadow"
    failed_before = _refreshes("failed")

    result, tenant_checks, _ = await _run_probe(temporal_client, ProbeInput(value="x", team_id=42))

    assert result == ["ran x", "ran x"]
    assert tenant_checks == {"unavailable": 1}
    await sync_to_async(wait_until)(lambda: _refreshes("failed") == failed_before + 1)


@pytest.mark.asyncio
async def test_off_reads_nothing_and_counts_nothing(temporal_client: Client, settings, clock: FakeClock) -> None:
    settings.TEMPORAL_ORGANIZATION_ADMISSION_MODE = "off"
    refreshes_before = (_refreshes("succeeded"), _refreshes("failed"))

    result, tenant_checks, bare_checks = await _run_probe(temporal_client, ProbeInput(value="x", team_id=42))

    assert result == ["ran x", "ran x"]
    assert tenant_checks == {}
    assert bare_checks == {}
    assert (_refreshes("succeeded"), _refreshes("failed")) == refreshes_before


@pytest.mark.parametrize("mode", ["enforce", "Shadow", ""])
def test_worker_refuses_an_unknown_mode(settings, mode: str) -> None:
    settings.TEMPORAL_ORGANIZATION_ADMISSION_MODE = mode

    with pytest.raises(ValueError):
        OrganizationAdmissionInterceptor()


class PydanticProbeInput(BaseModel):
    value: str
    team_id: int | None = None


@pytest.mark.parametrize(
    "args,expected",
    [
        ([ProbeInput(value="x", team_id=7)], (7, None)),
        ([PydanticProbeInput(value="x", team_id=7)], (7, None)),
        ([ProbeInput(value="x", organization_id="org")], (None, "org")),
        ([PydanticProbeInput(value="x", team_id=7), "extra"], (None, None)),
        (["x"], (None, None)),
    ],
)
def test_tenant_is_read_from_a_single_dataclass_or_pydantic_input(args: list, expected: tuple) -> None:
    input = ExecuteActivityInput(fn=tenant_probe_activity, args=args, executor=None, headers={})

    assert _tenant_of(input) == expected
