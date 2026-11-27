import uuid
import logging
import datetime as dt
from dataclasses import dataclass

import pytest

from asgiref.sync import sync_to_async
from prometheus_client import REGISTRY
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Organization, Team, organization_admission
from posthog.models.organization_admission import OrganizationAdmission
from posthog.temporal.common.interceptor import is_task_queue_supported
from posthog.temporal.common.worker import interceptor_classes

OUTCOMES = ("admitted", "would_skip", "unresolved", "error")


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


@pytest.fixture(autouse=True)
def fresh_admission(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    monkeypatch.setattr(organization_admission, "ORGANIZATION_ADMISSION", OrganizationAdmission())


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
    temporal_client: Client, settings, is_active: bool | None, by_organization: bool, expected: str
) -> None:
    settings.TEMPORAL_ORGANIZATION_ADMISSION_MODE = "shadow"
    team = await _team_in_organization(is_active)
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
@pytest.mark.parametrize("team_id", [None, 0])
async def test_shadow_counts_a_tenant_that_does_not_resolve(temporal_client: Client, settings, team_id) -> None:
    settings.TEMPORAL_ORGANIZATION_ADMISSION_MODE = "shadow"

    result, tenant_checks, _ = await _run_probe(temporal_client, ProbeInput(value="x", team_id=team_id))

    assert result == ["ran x", "ran x"]
    assert tenant_checks == {"unresolved": 1}


@pytest.mark.asyncio
async def test_shadow_runs_the_activity_when_the_lookup_fails(temporal_client: Client, settings) -> None:
    settings.TEMPORAL_ORGANIZATION_ADMISSION_MODE = "shadow"

    result, tenant_checks, _ = await _run_probe(temporal_client, ProbeInput(value="x", team_id=42))

    assert result == ["ran x", "ran x"]
    assert tenant_checks == {"error": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["off", "enforce"])
async def test_off_reads_nothing_and_counts_nothing(temporal_client: Client, settings, mode: str) -> None:
    settings.TEMPORAL_ORGANIZATION_ADMISSION_MODE = mode

    result, tenant_checks, bare_checks = await _run_probe(temporal_client, ProbeInput(value="x", team_id=42))

    assert result == ["ran x", "ran x"]
    assert tenant_checks == {}
    assert bare_checks == {}
