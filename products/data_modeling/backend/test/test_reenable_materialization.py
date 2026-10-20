from datetime import timedelta
from io import StringIO

from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import call_command

from parameterized import parameterized
from temporalio.service import RPCError, RPCStatusCode

from products.data_modeling.backend.models import DAG, Node
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import NodeType
from products.data_modeling.backend.test.helpers import no_existing_schedules

GET_V2_DAG_IDS = "products.data_modeling.backend.schedule.get_v2_scheduled_dag_ids"
RECONCILE = "products.data_modeling.backend.logic.schedule_reconcile"


class TestReenableMaterialization(BaseTest):
    def _saved_query(self, name: str, *, with_node: bool = True, deleted: bool = False) -> DataWarehouseSavedQuery:
        saved_query = DataWarehouseSavedQuery.objects.create(
            name=name,
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            is_materialized=False,
            sync_frequency_interval=timedelta(hours=12),
            deleted=deleted,
        )
        if with_node:
            Node.objects.create(team=self.team, dag=self.dag, saved_query=saved_query, type=NodeType.VIEW)
        return saved_query

    def setUp(self):
        super().setUp()
        self.dag = DAG.objects.create(team=self.team, name="Default")

    def test_dry_run_changes_nothing(self):
        switched_off = self._saved_query("switched_off")
        call_command("reenable_materialization", saved_query_ids=str(switched_off.id), stdout=StringIO())
        switched_off.refresh_from_db()
        assert switched_off.is_materialized is False

    @parameterized.expand(
        [
            ("tier_created", None, True, NodeType.MAT_VIEW, "Re-enabled 1, failed 1."),
            (
                "tier_create_fails",
                RPCError("connection reset", RPCStatusCode.UNAVAILABLE, b""),
                False,
                NodeType.VIEW,
                "Re-enabled 0, failed 2.",
            ),
        ]
    )
    def test_apply_reenables_only_live_queries_that_can_be_scheduled(
        self,
        _name: str,
        create_error: Exception | None,
        expected_materialized: bool,
        expected_node_type: NodeType,
        expected_summary: str,
    ):
        switched_off = self._saved_query("switched_off")
        deleted = self._saved_query("deleted", deleted=True)
        nodeless = self._saved_query("nodeless", with_node=False)
        out = StringIO()
        with (
            mock.patch(GET_V2_DAG_IDS, return_value={str(self.dag.id)}),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=no_existing_schedules())),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock(side_effect=create_error)) as create,
            self.captureOnCommitCallbacks(execute=True),
        ):
            call_command(
                "reenable_materialization",
                saved_query_ids=",".join(str(sq.id) for sq in (switched_off, deleted, nodeless)),
                apply=True,
                stdout=out,
            )

        for saved_query in (switched_off, deleted, nodeless):
            saved_query.refresh_from_db()
        node = Node.objects.get(saved_query=switched_off)
        assert create.call_args.kwargs["schedule"].action.args[0]["node_ids"] == [str(node.id)]
        assert switched_off.is_materialized is expected_materialized
        assert node.type == expected_node_type
        assert deleted.is_materialized is False
        assert nodeless.is_materialized is False
        assert expected_summary in out.getvalue()

    @parameterized.expand([("ctrl_c", KeyboardInterrupt), ("exit", SystemExit)])
    def test_interrupted_apply_leaves_the_query_off_for_the_next_run(
        self, _name: str, interruption: type[BaseException]
    ):
        switched_off = self._saved_query("switched_off")
        with (
            mock.patch(GET_V2_DAG_IDS, return_value={str(self.dag.id)}),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=no_existing_schedules())),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock(side_effect=interruption)),
            self.assertRaises(interruption),
        ):
            call_command(
                "reenable_materialization", saved_query_ids=str(switched_off.id), apply=True, stdout=StringIO()
            )

        switched_off.refresh_from_db()
        assert switched_off.is_materialized is False
