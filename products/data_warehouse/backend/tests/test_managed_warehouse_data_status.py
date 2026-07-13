from uuid import uuid4

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.ducklake.models import DuckgresSinkSchemaState

from products.data_warehouse.backend.logic.managed_warehouse_data_status import (
    QueueTailStatus,
    ReadinessState,
    source_table_readiness,
)


class TestSourceTableReadiness(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "persistent_failure_overrides_pending_batches",
                DuckgresSinkSchemaState.State.BACKFILLING,
                3,
                {"pending_batches": 4, "oldest_pending_at": None, "last_applied_at": None},
                True,
                "needs_attention",
            ),
            (
                "primed_schema_with_pending_batches_is_catching_up",
                DuckgresSinkSchemaState.State.PRIMED,
                0,
                {"pending_batches": 2, "oldest_pending_at": None, "last_applied_at": None},
                True,
                "catching_up",
            ),
            (
                "primed_schema_without_pending_batches_is_up_to_date",
                DuckgresSinkSchemaState.State.PRIMED,
                0,
                {"pending_batches": 0, "oldest_pending_at": None, "last_applied_at": None},
                True,
                "up_to_date",
            ),
            (
                "queue_outage_does_not_report_up_to_date",
                DuckgresSinkSchemaState.State.PRIMED,
                0,
                None,
                False,
                "unknown",
            ),
        ]
    )
    def test_state_precedence(
        self,
        _name: str,
        lifecycle_state: str,
        consecutive_failures: int,
        queue_status: QueueTailStatus | None,
        queue_available: bool,
        expected_readiness: ReadinessState,
    ) -> None:
        state = DuckgresSinkSchemaState(
            team_id=1,
            schema_id=uuid4(),
            state=lifecycle_state,
            consecutive_failures=consecutive_failures,
        )

        readiness, _ = source_table_readiness(state, queue_status, queue_available)

        assert readiness == expected_readiness
