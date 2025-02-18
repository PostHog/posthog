from rest_framework import status

from posthog.test.base import APIBaseTest
from posthog.warehouse.models import DataWarehouseFolder


class TestDataWarehouseFolderAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/warehouse_folders/"

    def test_create_folder(self):
        response = self.client.post(
            self.base_url,
            {
                "name": "MyFolder",
                "items": [],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "MyFolder")
        self.assertEqual(response.json()["items"], [])
        self.assertIsNone(response.json()["parent"])

        folder = DataWarehouseFolder.objects.get(id=response.json()["id"])
        self.assertEqual(folder.name, "MyFolder")
        self.assertEqual(folder.team, self.team)
        self.assertEqual(folder.created_by, self.user)

    def test_create_nested_folder(self):
        parent = DataWarehouseFolder.objects.create(name="ParentFolder", team=self.team, created_by=self.user)

        response = self.client.post(
            self.base_url,
            {"name": "ChildFolder", "items": [], "parent": str(parent.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "ChildFolder")
        self.assertEqual(response.json()["parent"], str(parent.id))

    def test_cannot_create_duplicate_folder(self):
        DataWarehouseFolder.objects.create(name="MyFolder", team=self.team, created_by=self.user)

        response = self.client.post(
            self.base_url,
            {
                "name": "MyFolder",
                "items": [],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("folder with this name already exists", response.json()["detail"].lower())

    def test_list_folders(self):
        DataWarehouseFolder.objects.create(name="Folder1", team=self.team, created_by=self.user)
        DataWarehouseFolder.objects.create(name="Folder2", team=self.team, created_by=self.user)

        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)
        self.assertEqual(response.json()["results"][0]["name"], "Folder1")
        self.assertEqual(response.json()["results"][1]["name"], "Folder2")

    def test_retrieve_folder(self):
        folder = DataWarehouseFolder.objects.create(name="MyFolder", team=self.team, created_by=self.user)

        response = self.client.get(f"{self.base_url}{folder.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "MyFolder")
        self.assertEqual(response.json()["items"], [])

    def test_update_folder(self):
        folder = DataWarehouseFolder.objects.create(name="OldName", team=self.team, created_by=self.user)

        response = self.client.patch(
            f"{self.base_url}{folder.id}/",
            {
                "name": "NewName",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "NewName")

        folder.refresh_from_db()
        self.assertEqual(folder.name, "NewName")

    def test_delete_folder(self):
        folder = DataWarehouseFolder.objects.create(name="ToDelete", team=self.team, created_by=self.user)

        response = self.client.delete(f"{self.base_url}{folder.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        with self.assertRaises(DataWarehouseFolder.DoesNotExist):
            DataWarehouseFolder.objects.get(id=folder.id)

    def test_cannot_access_other_team_folders(self):
        other_team = self.create_team_with_organization(organization=self.organization)
        folder = DataWarehouseFolder.objects.create(name="OtherTeamFolder", team=other_team, created_by=self.user)

        response = self.client.get(f"{self.base_url}{folder.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_create_folder_with_invalid_name(self):
        response = self.client.post(
            self.base_url,
            {"name": "Invalid Name", "items": []},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            "invalid name is not a valid folder name. folder names can only contain letters, numbers or '_' ",
            response.json()["detail"].lower(),
        )
