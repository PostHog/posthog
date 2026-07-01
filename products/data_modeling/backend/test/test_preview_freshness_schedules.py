from datetime import timedelta
from io import StringIO

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import call_command

from products.data_modeling.backend.logic.node_frequency import set_frequency_target
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType

M15 = timedelta(minutes=15)


def _table_node(team, dag, name, properties):
    return Node.objects.create(team=team, dag=dag, name=name, type=NodeType.TABLE, properties=properties)


def _saved_query_node(team, dag, name, node_type):
    saved_query = DataWarehouseSavedQuery.objects.create(
        name=name, team=team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
    )
    return Node.objects.create(team=team, dag=dag, saved_query=saved_query, type=node_type)


@pytest.mark.django_db
class TestPreviewFreshnessSchedules(BaseTest):
    def test_previews_tiers_without_touching_any_schedule(self):
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        matview = _saved_query_node(self.team, dag, "mv", NodeType.MAT_VIEW)
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=matview)
        Edge.objects.create(team=self.team, dag=dag, source=matview, target=endpoint)
        set_frequency_target(endpoint, M15)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                return
                yield  # pragma: no cover — empty async generator

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        module = "products.data_modeling.backend.logic.schedule_reconcile"
        out = StringIO()
        with (
            mock.patch(f"{module}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{module}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{module}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{module}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            call_command("preview_freshness_schedules", "--team-id", str(self.team.pk), stdout=out)

        # dry-run must not create, update, or delete any schedule
        create.assert_not_called()
        update.assert_not_called()
        delete.assert_not_called()

        output = out.getvalue()
        self.assertIn("CREATE", output)
        self.assertIn("0:15:00", output)
        self.assertIn("dry run", output)
