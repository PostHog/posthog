from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest import mock

from parameterized import parameterized
from rest_framework import status

from products.data_modeling.backend.logic.schedule_reconcile import DagScheduleTeardown
from products.data_modeling.backend.models import DAG, Node, NodeType

VIEW = "products.data_modeling.backend.presentation.views.dag"


def _teardown(*, ok: bool) -> DagScheduleTeardown:
    return DagScheduleTeardown(ok=ok, deleted=())


class TestDAGViewSet(APIBaseTest):
    def test_list_dags(self):
        DAG.objects.create(team=self.team, name="my_dag")
        DAG.objects.create(team=self.team, name="another_dag")

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_dags/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        names = [d["name"] for d in response.json()["results"]]
        self.assertEqual(names, ["another_dag", "my_dag"])

    def test_create_dag(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_dags/",
            {"name": "new_dag", "description": "A test DAG"},
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "new_dag")
        self.assertEqual(response.json()["description"], "A test DAG")
        self.assertEqual(response.json()["node_count"], 0)
        self.assertTrue(DAG.objects.filter(team=self.team, name="new_dag").exists())

    def test_retrieve_dag(self):
        dag = DAG.objects.create(team=self.team, name="my_dag", description="desc")
        Node.objects.create(team=self.team, dag=dag, name="events", type=NodeType.TABLE)

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "my_dag")
        self.assertEqual(response.json()["node_count"], 1)

    def test_partial_update_dag(self):
        dag = DAG.objects.create(team=self.team, name="my_dag")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/",
            {"description": "updated description"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["description"], "updated description")

    def test_delete_dag(self):
        dag = DAG.objects.create(team=self.team, name="my_dag")

        with mock.patch(f"{VIEW}.delete_dag_schedules", return_value=_teardown(ok=True)) as teardown:
            response = self.client.delete(f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(DAG.objects.filter(team=self.team, id=dag.id).exists())
        teardown.assert_called_once_with(str(dag.id))

    def test_dag_survives_a_failed_schedule_teardown(self):
        dag = DAG.objects.create(team=self.team, name="my_dag")

        with mock.patch(f"{VIEW}.delete_dag_schedules", return_value=_teardown(ok=False)):
            response = self.client.delete(f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/")

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertTrue(DAG.objects.filter(team=self.team, id=dag.id).exists())

    def test_cannot_delete_default_dag(self):
        dag = DAG.get_or_create_default(self.team)

        response = self.client.delete(f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(DAG.objects.filter(team=self.team, id=dag.id).exists())

    def test_cannot_rename_default_dag(self):
        dag = DAG.get_or_create_default(self.team)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/",
            {"name": "renamed"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        dag.refresh_from_db()
        self.assertEqual(dag.name, "Default")

    def test_cannot_delete_managed_dag(self):
        dag = DAG.get_or_create_revenue_analytics(self.team)

        response = self.client.delete(f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(DAG.objects.filter(team=self.team, id=dag.id).exists())

    def test_cannot_rename_managed_dag(self):
        dag = DAG.get_or_create_revenue_analytics(self.team)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/",
            {"name": "renamed"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        dag.refresh_from_db()
        self.assertEqual(dag.name, "PostHog Revenue Analytics")

    def test_cannot_edit_managed_dag(self):
        dag = DAG.get_or_create_revenue_analytics(self.team)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/",
            {"description": "updated description"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        dag.refresh_from_db()
        self.assertEqual(dag.description, "")

    def test_cannot_create_dag_with_reserved_name(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_dags/",
            {"name": "PostHog Revenue Analytics"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(DAG.objects.filter(team=self.team, name="PostHog Revenue Analytics").exists())

    @parameterized.expand(
        [
            ("escape", "evil\x1b[2Kreplaced"),
            ("carriage_return", "evil\rreplaced"),
            ("newline", "evil\nreplaced"),
            ("null", "evil\x00replaced"),
            ("delete", "evil\x7freplaced"),
        ]
    )
    def test_cannot_create_dag_with_control_characters_in_name(self, _name, dag_name):
        # DAG names are echoed into management-command output and the confirmation prompt of
        # destructive fleet tooling; a control character there rewrites what an operator reads
        # before typing "y". NUL additionally reaches Postgres as a driver-level DataError (a 500)
        # without this guard — the name is never queried back here for that reason.
        before = DAG.objects.filter(team=self.team).count()

        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_dags/",
            {"name": dag_name},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(DAG.objects.filter(team=self.team).count(), before)

    def test_cannot_rename_dag_to_a_name_with_control_characters(self):
        dag = DAG.objects.create(team=self.team, name="my_dag")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/",
            {"name": "my_dag\x1b[2Kevil"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        dag.refresh_from_db()
        self.assertEqual(dag.name, "my_dag")

    def test_ordinary_punctuation_in_a_name_is_still_allowed(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_dags/",
            {"name": "Ünïcode — dbt/staging (v2)"},
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_cannot_rename_dag_to_reserved_name(self):
        dag = DAG.objects.create(team=self.team, name="my_dag")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/",
            {"name": "PostHog Revenue Analytics"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        dag.refresh_from_db()
        self.assertEqual(dag.name, "my_dag")

    @parameterized.expand([("tiered", True), ("not_tiered", False)])
    def test_frequency_managed_by_nodes_tracks_tiered_schedules_flag(self, _name, enabled):
        DAG.objects.create(team=self.team, name="my_dag")
        DAG.objects.create(team=self.team, name="another_dag")

        with mock.patch(
            "products.data_modeling.backend.presentation.views.dag.tiered_schedules_enabled",
            return_value=enabled,
        ) as mock_flag:
            response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_dags/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([d["frequency_managed_by_nodes"] for d in response.json()["results"]], [enabled, enabled])
        # The flag is team-scoped, so it must be resolved once per request, not per DAG row.
        mock_flag.assert_called_once()

    def test_cannot_set_sync_frequency_on_tiered_team(self):
        dag = DAG.objects.create(team=self.team, name="my_dag")
        interval_before = dag.sync_frequency_interval

        with mock.patch(
            "products.data_modeling.backend.presentation.views.dag.tiered_schedules_enabled",
            return_value=True,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/",
                {"sync_frequency": "15min"},
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("managed per model", response.json()["detail"])
        dag.refresh_from_db()
        self.assertEqual(dag.sync_frequency_interval, interval_before)

    def test_can_still_rename_dag_on_tiered_team(self):
        dag = DAG.objects.create(team=self.team, name="my_dag")

        with mock.patch(
            "products.data_modeling.backend.presentation.views.dag.tiered_schedules_enabled",
            return_value=True,
        ):
            # The frontend spreads the whole DAG into the PATCH, echoing the current
            # sync_frequency back unchanged — that echo must not trip the tiered rejection.
            response = self.client.patch(
                f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/",
                {"name": "renamed", "description": "still editable", "sync_frequency": "24hour"},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        dag.refresh_from_db()
        self.assertEqual(dag.name, "renamed")
        self.assertEqual(dag.description, "still editable")
        self.assertEqual(dag.sync_frequency_interval, timedelta(days=1))

    def test_can_set_sync_frequency_on_non_tiered_team(self):
        dag = DAG.objects.create(team=self.team, name="my_dag")

        with mock.patch(
            "products.data_modeling.backend.presentation.views.dag.tiered_schedules_enabled",
            return_value=False,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/",
                {"sync_frequency": "15min"},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["sync_frequency"], "15min")
        dag.refresh_from_db()
        self.assertIsNotNone(dag.sync_frequency_interval)

    def test_node_count_reflects_nodes(self):
        dag = DAG.objects.create(team=self.team, name="my_dag")
        Node.objects.create(team=self.team, dag=dag, name="events", type=NodeType.TABLE)
        Node.objects.create(team=self.team, dag=dag, name="persons", type=NodeType.TABLE)

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/")

        self.assertEqual(response.json()["node_count"], 2)
