from posthog.test.base import APIBaseTest

from rest_framework import status

from products.data_modeling.backend.models import DAG, Node, NodeType


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

    def test_delete_not_allowed(self):
        dag = DAG.objects.create(team=self.team, name="my_dag")

        response = self.client.delete(f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/")

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_node_count_reflects_nodes(self):
        dag = DAG.objects.create(team=self.team, name="my_dag")
        Node.objects.create(team=self.team, dag=dag, name="events", type=NodeType.TABLE)
        Node.objects.create(team=self.team, dag=dag, name="persons", type=NodeType.TABLE)

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_dags/{dag.id}/")

        self.assertEqual(response.json()["node_count"], 2)
