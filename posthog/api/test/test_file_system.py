from rest_framework import status
from posthog.test.base import APIBaseTest
from posthog.models import FeatureFlag, Dashboard, Experiment, Insight, Notebook
from posthog.models.file_system import FileSystem, FileSystemType


class TestFileSystemAPI(APIBaseTest):
    def test_list_files_initially_empty(self):
        """
        When no FileSystem objects exist in the DB for the team, the list should be empty.
        """
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        response_data = response.json()
        self.assertEqual(response_data["count"], 0)
        self.assertEqual(response_data["results"], [])

    def test_create_file(self):
        """
        Ensure that we can create a FileSystem object for our team.
        """
        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system/",
            {"path": "MyFolder/Document.txt", "type": "doc-file", "meta": {"description": "A test file"}},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())

        response_data = response.json()
        self.assertIn("id", response_data)
        self.assertEqual(response_data["path"], "MyFolder/Document.txt")
        self.assertEqual(response_data["type"], "doc-file")
        self.assertDictEqual(response_data["meta"], {"description": "A test file"})
        self.assertEqual(response_data["created_by"]["id"], self.user.pk)

    def test_retrieve_file(self):
        """
        Test retrieving a single FileSystem object by ID.
        """
        file_obj = FileSystem.objects.create(
            team=self.team,
            path="MyFolder/RetrievedFile.txt",
            type="test-type",
            created_by=self.user,
        )
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/{file_obj.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        response_data = response.json()
        self.assertEqual(response_data["id"], str(file_obj.id))
        self.assertEqual(response_data["path"], "MyFolder/RetrievedFile.txt")
        self.assertEqual(response_data["type"], "test-type")

    def test_update_file(self):
        """
        Test updating an existing FileSystem object.
        """
        file_obj = FileSystem.objects.create(
            team=self.team, path="OldPath/file.txt", type="old-type", created_by=self.user
        )

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/file_system/{file_obj.pk}/",
            {"path": "NewPath/file.txt", "type": "new-type"},
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK, update_response.json())
        updated_data = update_response.json()
        self.assertEqual(updated_data["path"], "NewPath/file.txt")
        self.assertEqual(updated_data["type"], "new-type")

        file_obj.refresh_from_db()
        self.assertEqual(file_obj.path, "NewPath/file.txt")
        self.assertEqual(file_obj.type, "new-type")

    def test_delete_file(self):
        """
        Test deleting a FileSystem object.
        """
        file_obj = FileSystem.objects.create(
            team=self.team, path="DeleteMe/file.txt", type="temp", created_by=self.user
        )
        delete_response = self.client.delete(f"/api/projects/{self.team.id}/file_system/{file_obj.pk}/")
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(FileSystem.objects.filter(pk=file_obj.pk).exists())

    def test_unfiled_endpoint_no_content(self):
        """
        If there are no relevant items to create (e.g. no FeatureFlags, Experiments, etc.),
        'unfiled' should return an empty list and create nothing in the DB.
        """
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/unfiled/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        data = response.json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])
        self.assertEqual(FileSystem.objects.count(), 0)

    def test_unfiled_endpoint_with_content(self):
        """
        If we create some FeatureFlags, Experiments, Dashboards, Insights, or Notebooks,
        the 'unfiled' endpoint should create them in FileSystem and return them.
        """
        feature_flag = FeatureFlag.objects.create(team=self.team, name="Beta Feature", created_by=self.user)
        Experiment.objects.create(team=self.team, name="Experiment #1", created_by=self.user, feature_flag=feature_flag)
        Dashboard.objects.create(team=self.team, name="User Dashboard", created_by=self.user)
        Insight.objects.create(team=self.team, saved=True, name="Marketing Insight", created_by=self.user)
        Notebook.objects.create(team=self.team, title="Data Exploration", created_by=self.user)

        response = self.client.get(f"/api/projects/{self.team.id}/file_system/unfiled/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        data = response.json()
        results = data["results"]
        self.assertEqual(len(results), 5, results)
        self.assertEqual(FileSystem.objects.count(), 5)

        # Check that each type is present
        types = [item["type"] for item in results]
        self.assertIn(FileSystemType.FEATURE_FLAG, types)
        self.assertIn(FileSystemType.EXPERIMENT, types)
        self.assertIn(FileSystemType.DASHBOARD, types)
        self.assertIn(FileSystemType.INSIGHT, types)
        self.assertIn(FileSystemType.NOTEBOOK, types)

    def test_unfiled_endpoint_with_type_filtering(self):
        """
        Ensure that the 'type' query parameter filters creation to a single type.
        """
        flag = FeatureFlag.objects.create(team=self.team, name="Only Flag", created_by=self.user)
        Experiment.objects.create(team=self.team, name="Experiment #1", feature_flag=flag, created_by=self.user)

        # Filter for feature_flag only
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/unfiled/?type=feature_flag")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(FileSystem.objects.count(), 1)
        self.assertEqual(data["results"][0]["type"], FileSystemType.FEATURE_FLAG)

        # Check that no experiment was created
        self.assertFalse(FileSystem.objects.filter(type=FileSystemType.EXPERIMENT).exists())

    def test_unfiled_endpoint_is_idempotent(self):
        """
        Calling the unfiled endpoint multiple times should not create duplicate FileSystem rows
        for the same objects.
        """
        FeatureFlag.objects.create(team=self.team, name="Beta Feature", created_by=self.user)
        first_response = self.client.get(f"/api/projects/{self.team.id}/file_system/unfiled/")
        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(first_response.json()["count"], 1)
        self.assertEqual(FileSystem.objects.count(), 1)

        # Second call
        second_response = self.client.get(f"/api/projects/{self.team.id}/file_system/unfiled/")
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.json()["count"], 0, second_response.json())  # No new items
        self.assertEqual(FileSystem.objects.count(), 1)

    def test_search_files_by_path(self):
        """
        Ensure the search functionality is working on the 'path' field.
        """
        FileSystem.objects.create(team=self.team, path="Analytics/Report 1", type="report", created_by=self.user)
        FileSystem.objects.create(team=self.team, path="Analytics/Report 2", type="report", created_by=self.user)
        FileSystem.objects.create(team=self.team, path="Random/Other File", type="misc", created_by=self.user)

        response = self.client.get(f"/api/projects/{self.team.id}/file_system/?search=Analytics")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        data = response.json()
        self.assertEqual(data["count"], 2)
        paths = {item["path"] for item in data["results"]}
        self.assertSetEqual(paths, {"Analytics/Report 1", "Analytics/Report 2"})

        # Searching for something else
        response2 = self.client.get(f"/api/projects/{self.team.id}/file_system/?search=Random")
        self.assertEqual(response2.status_code, status.HTTP_200_OK, response2.json())
        data2 = response2.json()
        self.assertEqual(data2["count"], 1)
        self.assertEqual(data2["results"][0]["path"], "Random/Other File")
