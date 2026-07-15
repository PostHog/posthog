import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.signup_enrichment.workflow import (
    SignupEnrichmentInputs,
    SignupEnrichmentWorkflow,
    enrich_signup_organization_activity,
)

from products.growth.backend.enrichment.fields import EnrichmentFields

pytestmark = pytest.mark.asyncio

_MODULE = "posthog.temporal.signup_enrichment.workflow"
_INPUTS = SignupEnrichmentInputs(organization_id="org-1", distinct_id="d1", domain="stripe.com")
_TASK_QUEUE = "signup-enrichment-test-queue"


def _events(pha_client: MagicMock, name: str) -> list:
    return [c for c in pha_client.capture.call_args_list if c.kwargs["event"] == name]


async def _run(enrich_side_effect) -> tuple[dict, MagicMock, AsyncMock, MagicMock]:
    pha_client = MagicMock()
    enrich = AsyncMock(side_effect=enrich_side_effect)
    with (
        patch(f"{_MODULE}.get_client", return_value=pha_client),
        patch(f"{_MODULE}.enrich_organization", enrich),
        patch(f"{_MODULE}._deterministic_company_type", return_value=None),
        patch(f"{_MODULE}.capture_signup_enrichment_snapshot") as snapshot,
        patch("posthog.models.Organization.objects") as org_objects,
    ):
        org_objects.filter.return_value.exists.return_value = True
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=_TASK_QUEUE,
                workflows=[SignupEnrichmentWorkflow],
                activities=[enrich_signup_organization_activity],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                result = await env.client.execute_workflow(
                    SignupEnrichmentWorkflow.run,
                    _INPUTS,
                    id=f"signup-enrichment-{uuid.uuid4()}",
                    task_queue=_TASK_QUEUE,
                )
    return result, pha_client, enrich, snapshot


async def test_miss_then_recheck_upgrades_without_a_second_completed_event():
    fields = EnrichmentFields(company_type="STARTUP", headcount=130, industry="Fintech")
    result, pha_client, enrich, snapshot = await _run([None, fields])

    assert result == {"matched": True, "fields_filled": 3}
    assert enrich.await_count == 2
    # The is_recheck label is threaded through to the enrichment core: False first, True on recheck.
    assert enrich.await_args_list[0].kwargs["is_recheck"] is False
    assert enrich.await_args_list[1].kwargs["is_recheck"] is True
    # is_recheck=True skips the at-signup snapshot, so it is captured only on the first attempt.
    snapshot.assert_called_once()

    recheck = _events(pha_client, "signup_enrichment_recheck")
    assert len(recheck) == 1
    assert recheck[0].kwargs["properties"] == {
        "upgraded": True,
        "fields_filled": 3,
        "organization_id": "org-1",
    }
    # The launch signal fires exactly once — on the first attempt, unchanged.
    completed = _events(pha_client, "signup_enrichment_completed")
    assert len(completed) == 1
    assert completed[0].kwargs["properties"]["matched"] is False


async def test_match_on_first_attempt_skips_the_recheck():
    fields = EnrichmentFields(company_type="STARTUP", headcount=130)
    result, pha_client, enrich, snapshot = await _run([fields])

    assert result == {"matched": True, "fields_filled": 2}
    assert enrich.await_count == 1
    snapshot.assert_called_once()
    assert _events(pha_client, "signup_enrichment_recheck") == []
    assert len(_events(pha_client, "signup_enrichment_completed")) == 1


async def test_recheck_skips_deleted_organization():
    """The 4h recheck must not enrich or emit for an org deleted during the delay."""
    inputs = SignupEnrichmentInputs(
        organization_id="00000000-0000-0000-0000-00000000dead", distinct_id="d1", domain="gone.dev"
    )
    with (
        patch(f"{_MODULE}.enrich_organization") as enrich_mock,
        patch(f"{_MODULE}.get_client") as client_mock,
        patch("posthog.models.Organization.objects") as org_objects,
    ):
        org_objects.filter.return_value.exists.return_value = False
        result = await enrich_signup_organization_activity(inputs, is_recheck=True)
    assert result["org_deleted"] is True
    assert result["matched"] is False
    enrich_mock.assert_not_called()
    client_mock.assert_not_called()
