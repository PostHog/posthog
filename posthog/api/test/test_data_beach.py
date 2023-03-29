from rest_framework import status

from posthog.models import DataBeachTable, DataBeachTableEngine
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
)


class TestDataBeachApi(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def test_create_data_table(self, *args):
        response = self.client.post(
            f"/api/projects/{self.team.id}/data_beach_tables/",
            data={
                "name": "login_attempts",
                "fields": [
                    {"name": "username", "type": "String"},
                    {"name": "password", "type": "String"},
                ],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data_table = DataBeachTable.objects.get()
        self.assertEqual(data_table.name, "login_attempts")
        self.assertEqual(data_table.engine, DataBeachTableEngine.APPENDABLE)
        self.assertEqual(data_table.team, self.team)

        fields = data_table.fields.all()
        self.assertEqual(len(fields), 2)
        self.assertEqual(fields[0].name, "username")
        self.assertEqual(fields[0].type, "String")
        self.assertEqual(fields[0].team, self.team)
        self.assertEqual(response.json()["fields"][0]["name"], "username")
        self.assertEqual(response.json()["fields"][0]["type"], "String")
        self.assertEqual(response.json()["fields"][1]["name"], "password")
        self.assertEqual(response.json()["fields"][1]["type"], "String")

    def test_update_data_table(self, *args):
        response = self.client.post(
            f"/api/projects/{self.team.id}/data_beach_tables/",
            data={
                "name": "login_attempts",
                "fields": [
                    {"name": "username", "type": "String"},
                    {"name": "password", "type": "String"},
                ],
            },
        )
        data_table = DataBeachTable.objects.get()
        self.assertEqual(data_table.name, "login_attempts")
        initial_fields = data_table.fields.all()
        self.assertEqual(initial_fields[0].name, "username")

        # add a field, change the name
        response = self.client.patch(
            f"/api/projects/{self.team.id}/data_beach_tables/{data_table.pk}/",
            data={
                "name": "login_log",
                "fields": [
                    {"name": initial_fields[0].name, "type": "Integer", "id": initial_fields[0].pk},
                    {"name": initial_fields[1].name, "type": "Float", "id": initial_fields[1].pk},
                    {"name": "gatorade", "type": "Boolean"},
                ],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data_table = DataBeachTable.objects.get()
        self.assertEqual(data_table.name, "login_log")
        fields = data_table.fields.all()
        self.assertEqual(len(fields), 3)
        self.assertEqual(len(response.json()["fields"]), 3)
        self.assertEqual(fields[0].name, "username")
        self.assertEqual(fields[0].type, "Integer")
        self.assertEqual(fields[0].team, self.team)
        self.assertEqual(fields[0].pk, initial_fields[0].pk)
        self.assertEqual(fields[1].name, "password")
        self.assertEqual(fields[1].type, "Float")
        self.assertEqual(fields[1].team, self.team)
        self.assertEqual(fields[1].pk, initial_fields[1].pk)
        self.assertEqual(fields[2].name, "gatorade")
        self.assertEqual(fields[2].type, "Boolean")
        self.assertEqual(fields[2].team, self.team)

        # remove all fields
        response = self.client.patch(
            f"/api/projects/{self.team.id}/data_beach_tables/{data_table.pk}/",
            data={
                "name": "login_log",
                "fields": [
                    {"name": "totally_new", "type": "Boolean"},
                ],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        fields = DataBeachTable.objects.get().fields.all()
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0].name, "totally_new")

    def test_delete_data_table(self, *args):
        self.client.post(
            f"/api/projects/{self.team.id}/data_beach_tables/",
            data={
                "name": "login_attempts",
                "fields": [
                    {"name": "username", "type": "String"},
                    {"name": "password", "type": "String"},
                ],
            },
        )
        data_table = DataBeachTable.objects.get()
        response = self.client.delete(
            f"/api/projects/{self.team.id}/data_beach_tables/{data_table.pk}/",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        tables = DataBeachTable.objects.all()
        self.assertEqual(len(tables), 0)
