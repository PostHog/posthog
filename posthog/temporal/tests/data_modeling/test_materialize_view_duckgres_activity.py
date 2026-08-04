import pytest
import unittest.mock

from posthog.sync import database_sync_to_async
from posthog.temporal.data_modeling.activities.materialize_view_duckgres import (
    DuckgresShadowInputs,
    materialize_view_duckgres_activity,
)

from products.data_modeling.backend.facade.models import DataModelingJob
from products.managed_warehouse.backend.facade.contracts import CPUnavailableError

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


def _inputs(ateam, anode, adag, ajob) -> DuckgresShadowInputs:
    return DuckgresShadowInputs(
        team_id=ateam.pk,
        dag_id=str(adag.id),
        node_id=str(anode.id),
        job_id=str(ajob.id),
    )


class TestMaterializeViewDuckgresActivityFailurePosture:
    # A control-plane blip must not bury a real error signal in noise or suspend an
    # otherwise-healthy node — see the "duckgres control plane unreachable" incident.
    async def test_control_plane_outage_is_not_captured_or_suspended(
        self, activity_environment, ateam, anode, asaved_query, adag, ajob
    ):
        with (
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view_duckgres._compile_hogql_to_postgres_sql",
                side_effect=CPUnavailableError("duckgres control plane unreachable reading team state for team 1"),
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view_duckgres.capture_exception"
            ) as mock_capture,
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view_duckgres.maybe_suspend_node_for_engine"
            ) as mock_suspend,
        ):
            result = await activity_environment.run(
                materialize_view_duckgres_activity, _inputs(ateam, anode, adag, ajob)
            )

        assert result.error is not None
        mock_capture.assert_not_called()
        mock_suspend.assert_not_called()

        await database_sync_to_async(ajob.refresh_from_db)()
        assert ajob.status == DataModelingJob.Status.FAILED

    async def test_other_errors_are_still_captured_and_can_suspend(
        self, activity_environment, ateam, anode, asaved_query, adag, ajob
    ):
        with (
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view_duckgres._compile_hogql_to_postgres_sql",
                side_effect=ValueError("bad query"),
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view_duckgres.capture_exception"
            ) as mock_capture,
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.materialize_view_duckgres.maybe_suspend_node_for_engine",
                return_value=False,
            ) as mock_suspend,
        ):
            result = await activity_environment.run(
                materialize_view_duckgres_activity, _inputs(ateam, anode, adag, ajob)
            )

        assert result.error is not None
        mock_capture.assert_called_once()
        mock_suspend.assert_called_once()
