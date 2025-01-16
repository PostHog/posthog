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
                "name": "My Folder",
                "items": [],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "My Folder")
        self.assertEqual(response.json()["items"], [])
        self.assertIsNone(response.json()["parent"])

        folder = DataWarehouseFolder.objects.get(id=response.json()["id"])
        self.assertEqual(folder.name, "My Folder")
        self.assertEqual(folder.team, self.team)
        self.assertEqual(folder.created_by, self.user)

    def test_create_nested_folder(self):
        parent = DataWarehouseFolder.objects.create(name="Parent Folder", team=self.team, created_by=self.user)

        response = self.client.post(
            self.base_url,
            {"name": "Child Folder", "items": [], "parent": str(parent.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Child Folder")
        self.assertEqual(response.json()["parent"], str(parent.id))

    def test_cannot_create_duplicate_folder(self):
        DataWarehouseFolder.objects.create(name="My Folder", team=self.team, created_by=self.user)

        response = self.client.post(
            self.base_url,
            {
                "name": "My Folder",
                "items": [],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("folder with this name already exists", response.json()["detail"].lower())

    def test_list_folders(self):
        DataWarehouseFolder.objects.create(name="Folder 1", team=self.team, created_by=self.user)
        DataWarehouseFolder.objects.create(name="Folder 2", team=self.team, created_by=self.user)

        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)
        self.assertEqual(response.json()["results"][0]["name"], "Folder 1")
        self.assertEqual(response.json()["results"][1]["name"], "Folder 2")

    def test_retrieve_folder(self):
        folder = DataWarehouseFolder.objects.create(name="My Folder", team=self.team, created_by=self.user)

        response = self.client.get(f"{self.base_url}{folder.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "My Folder")
        self.assertEqual(response.json()["items"], [])

    def test_list_folders_with_subfolders(self):
        parent = DataWarehouseFolder.objects.create(name="Parent Folder", team=self.team, created_by=self.user)
        child = DataWarehouseFolder.objects.create(
            name="Child Folder", team=self.team, created_by=self.user, parent=parent
        )

        response = self.client.get(f"{self.base_url}?include_subfolders=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.json()["results"][0]["children"]), 1)
        self.assertEqual(response.json()["results"][0]["children"][0]["name"], "Child Folder")

        DataWarehouseFolder.objects.create(name="Grandchild Folder", team=self.team, created_by=self.user, parent=child)

        response = self.client.get(f"{self.base_url}?include_subfolders=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"][0]["children"]), 1)
        self.assertEqual(response.json()["results"][0]["children"][0]["name"], "Child Folder")
        self.assertEqual(response.json()["results"][0]["children"][0]["children"][0]["name"], "Grandchild Folder")

    def test_list_folders_with_subfolders_alphabetically(self):
        # Create folders in non-alphabetical order
        parent_z = DataWarehouseFolder.objects.create(name="Z Parent", team=self.team, created_by=self.user)
        parent_a = DataWarehouseFolder.objects.create(name="A Parent", team=self.team, created_by=self.user)

        # Create children in non-alphabetical order
        DataWarehouseFolder.objects.create(name="Z Child", team=self.team, created_by=self.user, parent=parent_z)
        DataWarehouseFolder.objects.create(name="A Child", team=self.team, created_by=self.user, parent=parent_z)
        DataWarehouseFolder.objects.create(name="M Child", team=self.team, created_by=self.user, parent=parent_a)
        DataWarehouseFolder.objects.create(name="B Child", team=self.team, created_by=self.user, parent=parent_a)

        response = self.client.get(f"{self.base_url}?include_subfolders=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.json()["results"]

        # Verify parents are alphabetically ordered
        self.assertEqual(results[0]["name"], "A Parent")
        self.assertEqual(results[1]["name"], "Z Parent")

        # Verify children within each parent are alphabetically ordered
        a_parent_children = results[0]["children"]
        self.assertEqual(a_parent_children[0]["name"], "B Child")
        self.assertEqual(a_parent_children[1]["name"], "M Child")

        z_parent_children = results[1]["children"]
        self.assertEqual(z_parent_children[0]["name"], "A Child")
        self.assertEqual(z_parent_children[1]["name"], "Z Child")

    def test_update_folder(self):
        folder = DataWarehouseFolder.objects.create(name="Old Name", team=self.team, created_by=self.user)

        response = self.client.patch(
            f"{self.base_url}{folder.id}/",
            {
                "name": "New Name",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "New Name")

        folder.refresh_from_db()
        self.assertEqual(folder.name, "New Name")

    def test_delete_folder(self):
        folder = DataWarehouseFolder.objects.create(name="To Delete", team=self.team, created_by=self.user)

        response = self.client.delete(f"{self.base_url}{folder.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        folder.refresh_from_db()
        self.assertTrue(folder.deleted)

    def test_cannot_access_other_team_folders(self):
        other_team = self.create_team_with_organization(organization=self.organization)
        folder = DataWarehouseFolder.objects.create(name="Other Team Folder", team=other_team, created_by=self.user)

        response = self.client.get(f"{self.base_url}{folder.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
