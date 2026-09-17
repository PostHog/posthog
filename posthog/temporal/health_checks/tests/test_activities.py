from collections.abc import Awaitable, Callable

import pytest

from prometheus_client import REGISTRY

from posthog.temporal.health_checks.activities import get_team_id_batches, run_health_check_batch
from posthog.temporal.health_checks.models import HealthCheckWorkflowInputs
from posthog.temporal.health_checks.registry import HealthCheckKindNotRegistered

UNREGISTERED_KIND = "not_in_this_image"


def _refusals() -> float:
    """Current value of the unregistered-kind tombstone counter in the default registry."""
    return (
        REGISTRY.get_sample_value(
            "posthog_tombstone_total",
            {"namespace": "health_checks", "operation": "unregistered_kind", "component": "registry"},
        )
        or 0.0
    )


class TestUnregisteredKind:
    @pytest.mark.asyncio
    async def test_refuses_a_kind_this_image_cannot_detect(self) -> None:
        # No database access: the guard has to run before the team query, so the whole run
        # fails instead of every batch it would otherwise fan out to.
        with pytest.raises(HealthCheckKindNotRegistered, match=UNREGISTERED_KIND):
            await get_team_id_batches(HealthCheckWorkflowInputs(name="Stub check", kind=UNREGISTERED_KIND))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "run_activity",
        [
            pytest.param(
                lambda: get_team_id_batches(HealthCheckWorkflowInputs(name="Stub check", kind=UNREGISTERED_KIND)),
                id="batching",
            ),
            pytest.param(lambda: run_health_check_batch([1], UNREGISTERED_KIND, False), id="batch"),
        ],
    )
    async def test_counts_the_refusal(self, run_activity: Callable[[], Awaitable[object]]) -> None:
        before = _refusals()

        with pytest.raises(HealthCheckKindNotRegistered):
            await run_activity()

        assert _refusals() == before + 1
