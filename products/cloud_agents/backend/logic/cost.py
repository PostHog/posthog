"""Turn the charges that Tasks reports for a task into the cost of a run. Pure, no database."""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from products.tasks.backend.facade.contracts import TaskRunBillingDTO

from ..facade.contracts import RunCostDTO, SandboxSessionUsageDTO
from ..facade.enums import BillingMode, InferenceBilling

_USD_PLACES: Final = Decimal("0.0001")
_SECONDS_PLACES: Final = Decimal("0.001")


def cents_to_usd(cents: int | None) -> Decimal | None:
    return None if cents is None else (Decimal(cents) / 100).quantize(_USD_PLACES)


def inference_usd(cost_cents: int | None, inference_billing: str) -> Decimal | None:
    # The customer pays the model provider directly for a run on their own credential, so PostHog has no cost to show.
    return cents_to_usd(cost_cents) if inference_billing == InferenceBilling.POSTHOG else None


def to_cost_dto(*, billable: bool, inference: str | None, billing: TaskRunBillingDTO | None) -> RunCostDTO:
    """The cost of a run. `inference` is the mode that the run was created with, for a run with no task yet."""
    billing_mode = BillingMode.BILLED if billable else BillingMode.UNBILLED
    if billing is None:
        return RunCostDTO(
            compute_usd=None,
            inference_usd=None,
            total_usd=None,
            vcpu_seconds=None,
            gib_seconds=None,
            billing_mode=billing_mode,
            inference_billing=InferenceBilling(inference) if inference else None,
            final=False,
        )
    compute_usd = cents_to_usd(billing.compute_cost_cents)
    inference_cost_usd = inference_usd(billing.inference_cost_cents, billing.inference_billing)
    return RunCostDTO(
        compute_usd=compute_usd,
        inference_usd=inference_cost_usd,
        total_usd=None if compute_usd is None else compute_usd + (inference_cost_usd or Decimal(0)),
        vcpu_seconds=billing.vcpu_seconds.quantize(_SECONDS_PLACES),
        gib_seconds=billing.gib_seconds.quantize(_SECONDS_PLACES),
        billing_mode=billing_mode,
        inference_billing=InferenceBilling(billing.inference_billing),
        final=billing.settled,
    )


def to_session_usage_dtos(billing: TaskRunBillingDTO) -> list[SandboxSessionUsageDTO]:
    return [
        SandboxSessionUsageDTO(
            vcpu=Decimal(str(session.cpu_cores)),
            memory_gib=Decimal(str(session.memory_gb)),
            started_at=session.started_at,
            ended_at=session.ended_at,
            seconds=session.seconds,
            cost_usd=cents_to_usd(session.cost_cents) or Decimal(0),
            waived=session.waived,
        )
        for session in billing.sessions
    ]
