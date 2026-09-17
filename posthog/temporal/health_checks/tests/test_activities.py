import pytest

from posthog.temporal.health_checks.activities import get_team_id_batches
from posthog.temporal.health_checks.models import HealthCheckWorkflowInputs
from posthog.temporal.health_checks.registry import HealthCheckKindNotRegistered


class TestGetTeamIdBatches:
    @pytest.mark.asyncio
    async def test_refuses_a_kind_this_image_cannot_detect(self) -> None:
        # No database access: the guard has to run before the team query, so the whole run
        # fails instead of every batch it would otherwise fan out to.
        with pytest.raises(HealthCheckKindNotRegistered, match="not_in_this_image"):
            await get_team_id_batches(HealthCheckWorkflowInputs(name="Stub check", kind="not_in_this_image"))
