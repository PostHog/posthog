from rest_framework import status
from posthog.api.file_system import has_permissions_to_access_tree_view
from posthog.test.base import APIBaseTest
from posthog.models import FeatureFlag, Dashboard, Experiment, Insight, Notebook
from posthog.models.file_system.file_system import FileSystem
from unittest.mock import patch
from rest_framework.exceptions import PermissionDenied


class TestFileSystemAPIPermissions(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = False
        self.user.save()

    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_permissions_no_staff_no_feature(self, mock_feature_flag):
        with self.assertRaises(PermissionDenied):
            has_permissions_to_access_tree_view(self.user, self.team)

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_permissions_no_staff_yes_feature(self, mock_feature_flag):
        try:
            has_permissions_to_access_tree_view(self.user, self.team)
        except Exception as e:
            self.fail(f"Permission check raised an exception unexpectedly: {e}")

    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_permissions_yes_staff_no_feature(self, mock_feature_flag):
        self.user.is_staff = True
        self.user.save()
        try:
            has_permissions_to_access_tree_view(self.user, self.team)
        except Exception as e:
            self.fail(f"Permission check raised an exception unexpectedly: {e}")

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_permissions_yes_staff_yes_feature(self, mock_feature_flag):
        self.user.is_staff = True
        self.user.save()
        try:
            has_permissions_to_access_tree_view(self.user, self.team)
        except Exception as e:
            self.fail(f"Permission check raised an exception unexpectedly: {e}")


class TestFileSystemAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # The user must be a staff user while we're beta testing
        self.user.is_staff = True
        self.user.save()

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

    def test_delete_folder_obj(self):
        """
        Test deleting a FileSystem folder.
        """
        folder_obj = FileSystem.objects.create(team=self.team, path="DeleteMe", type="folder", created_by=self.user)
        file1_obj = FileSystem.objects.create(
            team=self.team, path="DeleteMe/file.txt", type="temp", created_by=self.user
        )
        file2_obj = FileSystem.objects.create(
            team=self.team, path="DeleteMe/file.txt", type="temp", created_by=self.user
        )
        delete_response = self.client.delete(f"/api/projects/{self.team.id}/file_system/{folder_obj.pk}/")
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(FileSystem.objects.filter(pk=folder_obj.pk).exists())
        self.assertFalse(FileSystem.objects.filter(pk=file1_obj.pk).exists())
        self.assertFalse(FileSystem.objects.filter(pk=file2_obj.pk).exists())

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

    def test_unfiled_endpoint_is_idempotent(self):
        """
        Calling the unfiled endpoint multiple times should not create duplicate
        FileSystem rows for the same objects.
        """
        FeatureFlag.objects.create(team=self.team, key="Beta Feature", created_by=self.user)
        FileSystem.objects.all().delete()

        first_response = self.client.get(f"/api/projects/{self.team.id}/file_system/unfiled/")
        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(first_response.json()["count"], 1)  # 1 new "leaf" item
        # Check that there's exactly 1 *non-folder* item in DB
        self.assertEqual(FileSystem.objects.exclude(type="folder").count(), 1)

        # Second call => no new unfiled items
        second_response = self.client.get(f"/api/projects/{self.team.id}/file_system/unfiled/")
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.json()["count"], 0)  # No new items
        # Should still have just 1 *non-folder* item
        self.assertEqual(FileSystem.objects.exclude(type="folder").count(), 1)

    def test_unfiled_endpoint_with_content(self):
        """
        If we create some FeatureFlags, Experiments, Dashboards, Insights,
        or Notebooks, the 'unfiled' endpoint should create them in FileSystem
        and return them. We now exclude folder rows when counting total.
        """
        # Create 5 objects
        ff = FeatureFlag.objects.create(team=self.team, key="Beta Feature", created_by=self.user)
        Experiment.objects.create(team=self.team, name="Experiment #1", created_by=self.user, feature_flag=ff)
        Dashboard.objects.create(team=self.team, name="User Dashboard", created_by=self.user)
        Insight.objects.create(team=self.team, saved=True, name="Marketing Insight", created_by=self.user)
        Notebook.objects.create(team=self.team, title="Data Exploration", created_by=self.user)
        FileSystem.objects.all().delete()

        response = self.client.get(f"/api/projects/{self.team.id}/file_system/unfiled/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        data = response.json()
        results = data["results"]

        # We get 5 newly created "leaf" entries
        self.assertEqual(len(results), 5)
        # In the entire FileSystem table, ignoring 'folder' rows, we should also have 5
        self.assertEqual(FileSystem.objects.exclude(type="folder").count(), 5)

        # check that each type is present
        types = {item["type"] for item in results}
        self.assertIn("feature_flag", types)
        self.assertIn("experiment", types)
        self.assertIn("dashboard", types)
        self.assertIn("insight", types)
        self.assertIn("notebook", types)

    def test_unfiled_endpoint_with_type_filtering(self):
        """
        Ensure that the 'type' query parameter filters creation to a single type.
        """
        flag = FeatureFlag.objects.create(team=self.team, key="Only Flag", created_by=self.user)
        Experiment.objects.create(team=self.team, name="Experiment #1", feature_flag=flag, created_by=self.user)
        FileSystem.objects.all().delete()

        # Filter for feature_flag only => creates 1 new 'leaf' item
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/unfiled/?type=feature_flag")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        data = response.json()
        self.assertEqual(data["count"], 1)
        # Check we only have 1 non-folder item in DB
        self.assertEqual(FileSystem.objects.exclude(type="folder").count(), 1)

        # Verify that no experiment row was created
        self.assertFalse(
            FileSystem.objects.exclude(type="folder").filter(type="experiment").exists(),
            "Should not have created an experiment row yet!",
        )

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

    def test_depth_on_create_single_segment(self):
        """
        Creating a FileSystem with a single-segment path (like "Documents") should have depth=1.
        """
        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system/",
            {"path": "Documents", "type": "doc"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        created = response.json()
        self.assertEqual(created["path"], "Documents")
        self.assertEqual(created["depth"], 1)  # Single segment => depth=1

        # Double-check via DB
        file_obj = FileSystem.objects.get(id=created["id"])
        self.assertEqual(file_obj.depth, 1)

    def test_depth_on_create_multiple_segments(self):
        """
        Creating a FileSystem with multiple path segments should have depth equal to the number of segments.
        E.g. "Folder/Subfolder/File" => depth=3
        """
        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system/",
            {"path": "Folder/Subfolder/File", "type": "doc"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        created = response.json()
        self.assertEqual(created["path"], "Folder/Subfolder/File")
        self.assertEqual(created["depth"], 3)  # 3 segments

        # Verify in DB
        file_obj = FileSystem.objects.get(id=created["id"])
        self.assertEqual(file_obj.depth, 3)

    def test_depth_on_partial_update(self):
        """
        Updating an existing FileSystem object's path should recalculate depth.
        """
        file_obj = FileSystem.objects.create(
            team=self.team, path="OldPath/file.txt", type="test", created_by=self.user, depth=2
        )
        # Verify original depth in DB
        self.assertEqual(file_obj.depth, 2)

        # Now update the path to add or remove segments
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/file_system/{file_obj.pk}/",
            {"path": "NewPath/Subfolder/file.txt"},
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        updated_data = update_response.json()
        self.assertEqual(updated_data["path"], "NewPath/Subfolder/file.txt")
        self.assertEqual(updated_data["depth"], 3)  # Now 3 segments

        file_obj.refresh_from_db()
        self.assertEqual(file_obj.depth, 3)

    def test_depth_on_partial_update_reduced_segments(self):
        """
        If we reduce the number of segments via a partial update, depth should decrease.
        """
        file_obj = FileSystem.objects.create(team=self.team, path="A/B/C", type="test", created_by=self.user, depth=3)
        self.assertEqual(file_obj.depth, 3)

        # Update path to fewer segments
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/file_system/{file_obj.pk}/",
            {"path": "SingleSegment"},
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        updated_data = update_response.json()
        self.assertEqual(updated_data["path"], "SingleSegment")
        self.assertEqual(updated_data["depth"], 1)  # Single segment

        file_obj.refresh_from_db()
        self.assertEqual(file_obj.depth, 1)

    def test_depth_for_unfiled_items(self):
        """
        When unfiled items are created by the 'unfiled' endpoint, verify their depth is correct.
        By default, an unfiled FeatureFlag ends up with something like "Unfiled/Feature Flags/Flag Name" => depth=3
        """
        # Create a FeatureFlag
        FeatureFlag.objects.create(team=self.team, key="Beta Feature", created_by=self.user)
        FileSystem.objects.all().delete()

        # Call unfiled - that should create the new FileSystem item
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/unfiled/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        data = response.json()
        self.assertEqual(data["count"], 1)

        # Check the resulting item
        item = data["results"][0]
        self.assertEqual(item["path"], "Unfiled/Feature Flags/Beta Feature")
        self.assertEqual(item["depth"], 3)  # e.g. ["Unfiled", "Feature Flags", "Beta Feature"]

        # Double-check in DB
        fs_obj = FileSystem.objects.get(id=item["id"])
        self.assertEqual(fs_obj.depth, 3)

    def test_depth_for_unfiled_items_multiple_segments(self):
        """
        If an object name contains a slash, it should be escaped in the path, but still count as a single path segment.
        """
        # If a user enters something with a slash in the name...
        FeatureFlag.objects.create(team=self.team, key="Flag / With Slash", created_by=self.user)
        FileSystem.objects.all().delete()

        # This becomes "Unfiled/Feature Flags/Flag \/ With Slash"
        # but that is still 3 path segments from the perspective of split_path()
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/unfiled/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        data = response.json()
        self.assertEqual(data["count"], 1)

        item = data["results"][0]
        self.assertEqual(item["depth"], 3)  # "Unfiled" / "Feature Flags" / "Flag \/ With Slash"

    def test_list_by_depth(self):
        """
        Verify that passing ?depth=N returns only items with that depth.
        """
        # Create some FileSystem objects with various depths
        FileSystem.objects.create(team=self.team, path="OneSegment", depth=1, created_by=self.user)
        FileSystem.objects.create(team=self.team, path="Folder/Sub", depth=2, created_by=self.user)
        FileSystem.objects.create(team=self.team, path="Deep/Nested/Path", depth=3, created_by=self.user)

        # depth=2
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/?depth=2")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["path"], "Folder/Sub")

        # depth=3
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/?depth=3")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["path"], "Deep/Nested/Path")

    def test_list_by_parent(self):
        """
        Verify that passing ?parent=SomeFolder returns only items whose path starts with "SomeFolder/".
        """
        FileSystem.objects.create(team=self.team, path="RootItem", depth=1, created_by=self.user)
        FileSystem.objects.create(team=self.team, path="SomeFolder/File1", depth=2, created_by=self.user)
        FileSystem.objects.create(team=self.team, path="SomeFolder/SubFolder/File2", depth=3, created_by=self.user)
        FileSystem.objects.create(team=self.team, path="AnotherFolder/File3", depth=2, created_by=self.user)

        # Filter by ?parent=SomeFolder
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/?parent=SomeFolder")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 2, data["results"])
        paths = {obj["path"] for obj in data["results"]}
        # Should only include items that start with "SomeFolder/"
        self.assertIn("SomeFolder/File1", paths)
        self.assertIn("SomeFolder/SubFolder/File2", paths)
        self.assertNotIn("RootItem", paths)
        self.assertNotIn("AnotherFolder/File3", paths)

    def test_list_by_parent_and_depth(self):
        """
        If ?parent=SomeFolder and ?depth=2, we only want items that start with 'SomeFolder/'
        AND have depth=2.
        """
        FileSystem.objects.create(team=self.team, path="RootItem", depth=1, created_by=self.user)
        fs1 = FileSystem.objects.create(team=self.team, path="SomeFolder/File1", depth=2, created_by=self.user)
        fs2 = FileSystem.objects.create(
            team=self.team, path="SomeFolder/SubFolder/File2", depth=3, created_by=self.user
        )

        url = f"/api/projects/{self.team.id}/file_system/?parent=SomeFolder&depth=2"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        # Only 'File1' matches that filter
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["id"], str(fs1.id))

        # Double-check that 'File2' (depth=3) is excluded
        self.assertNotEqual(data["results"][0]["id"], str(fs2.id))

    def test_create_file_with_auto_folders(self):
        """
        Creating a deep path 'a/b/c/d/e' should auto-create folder entries for
        'a', 'a/b', 'a/b/c', 'a/b/c/d', if they don't already exist.
        """
        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system/",
            {
                "path": "a/b/c/d/e",
                "type": "doc-file",
                "meta": {"description": "Deep file"},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())

        # Final item:
        leaf = FileSystem.objects.get(path="a/b/c/d/e", team=self.team)
        self.assertEqual(leaf.depth, 5)
        self.assertEqual(leaf.type, "doc-file")

        # Check that folders exist
        folder_paths = ["a", "a/b", "a/b/c", "a/b/c/d"]
        for depth_index, folder_path in enumerate(folder_paths, start=1):
            folder = FileSystem.objects.get(path=folder_path, team=self.team)
            self.assertEqual(folder.depth, depth_index)
            self.assertEqual(folder.type, "folder")

    def test_move_files_and_folders(self):
        """
        Moving a folder should update all child paths correctly.
        """
        # Create a folder and some files inside it
        folder = FileSystem.objects.create(team=self.team, path="OldFolder", type="folder", created_by=self.user)
        file1 = FileSystem.objects.create(team=self.team, path="OldFolder/File1", type="doc", created_by=self.user)
        file2 = FileSystem.objects.create(team=self.team, path="OldFolder/File2", type="doc", created_by=self.user)

        # Move the folder
        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system/{folder.pk}/move",
            {"new_path": "NewFolder"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        # Check that the folder and files have been moved
        folder.refresh_from_db()
        self.assertEqual(folder.path, "NewFolder")

        file1.refresh_from_db()
        self.assertEqual(file1.path, "NewFolder/File1")

        file2.refresh_from_db()
        self.assertEqual(file2.path, "NewFolder/File2")

    def test_count_of_files(self):
        """
        Moving a folder should update all child paths correctly.
        """
        # Create a folder and some files inside it
        folder = FileSystem.objects.create(team=self.team, path="OldFolder", type="folder", created_by=self.user)
        FileSystem.objects.create(team=self.team, path="OldFolder/File1", type="doc", created_by=self.user)
        FileSystem.objects.create(team=self.team, path="OldFolder/File2", type="doc", created_by=self.user)

        # Move the folder
        response = self.client.post(f"/api/projects/{self.team.id}/file_system/{folder.pk}/count")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json()["count"], 2)

    def test_list_by_type_filter(self):
        """
        Ensure that the list endpoint filters results by the 'type' query parameter.
        """
        # Create several FileSystem items with different types
        FileSystem.objects.create(team=self.team, path="FileA.txt", type="doc", created_by=self.user)
        FileSystem.objects.create(team=self.team, path="FileB.txt", type="img", created_by=self.user)
        FileSystem.objects.create(team=self.team, path="FileC.txt", type="doc", created_by=self.user)

        # Filter by type 'doc'
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/?type=doc")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        # Expecting 2 items with type 'doc'
        self.assertEqual(data["count"], 2)
        for item in data["results"]:
            self.assertEqual(item["type"], "doc")

        response = self.client.get(f"/api/projects/{self.team.id}/file_system/?type__startswith=d")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        # Expecting 2 items with type starting with 'd'
        self.assertEqual(data["count"], 2)

    def test_search_files_by_ref(self):
        """
        Ensure that searching with the ?search= query param returns items matching on the 'ref' field.
        """
        # Create items with unique ref values
        FileSystem.objects.create(
            team=self.team, path="SomePath/File1", type="doc", ref="unique-ref-123", created_by=self.user
        )
        FileSystem.objects.create(
            team=self.team, path="OtherPath/File2", type="doc", ref="other-ref-456", created_by=self.user
        )
        # Using search to filter by part of the ref value
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/?search=unique-ref")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        # Expecting only the item with ref "unique-ref-123"
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["ref"], "unique-ref-123")

    def test_link_file_endpoint(self):
        """
        Test linking a file creates a new file with an updated path and that missing parent folders are auto-created.
        """
        # Create an original file.
        file_obj = FileSystem.objects.create(
            team=self.team,
            path="OriginalFile.txt",
            type="doc",
            created_by=self.user,
        )
        new_path = "NewFolder/NewFile.txt"
        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system/{file_obj.pk}/link",
            {"new_path": new_path},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        result = response.json()
        self.assertEqual(result["path"], new_path)
        # "NewFolder/NewFile.txt" should have a depth of 2.
        self.assertEqual(result["depth"], 2)
        # Ensure that the parent folder "NewFolder" was auto-created as a folder.
        self.assertTrue(FileSystem.objects.filter(team=self.team, path="NewFolder", type="folder").exists())

    def test_link_folder_endpoint(self):
        """
        Test linking a folder creates a new folder instance and also clones its child items with updated paths.
        """
        # Create a folder and a child file.
        folder_obj = FileSystem.objects.create(
            team=self.team,
            path="Folder1",
            type="folder",
            created_by=self.user,
        )
        FileSystem.objects.create(
            team=self.team,
            path="Folder1/Child.txt",
            type="doc",
            created_by=self.user,
        )
        new_path = "LinkedFolder"
        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system/{folder_obj.pk}/link",
            {"new_path": new_path},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        result = response.json()
        self.assertEqual(result["path"], new_path)
        # A single-segment folder should have depth 1.
        self.assertEqual(result["depth"], 1)
        # Verify that the child file was linked with its path updated.
        linked_child = FileSystem.objects.filter(team=self.team, path="LinkedFolder/Child.txt", type="doc").first()
        assert linked_child is not None
        self.assertEqual(linked_child.depth, 2)

    def test_link_folder_into_itself(self):
        """
        Test that linking a folder into itself is rejected.
        """
        folder_obj = FileSystem.objects.create(
            team=self.team,
            path="Folder2",
            type="folder",
            created_by=self.user,
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system/{folder_obj.pk}/link",
            {"new_path": "Folder2"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertIn("detail", response.json())
        self.assertEqual(response.json()["detail"], "Cannot link folder into itself")

    def test_assure_parent_folders(self):
        """
        Test that assure_parent_folders creates all missing parent folder entries for a given path.
        """
        # Clear existing FileSystem entries to start fresh.
        FileSystem.objects.all().delete()
        test_path = "A/B/C"
        # Import the function to be tested.
        from posthog.api.file_system import assure_parent_folders

        assure_parent_folders(test_path, self.team, self.user)

        # For the path "A/B/C", we expect the parent folders "A" and "A/B" to be created.
        folder_a = FileSystem.objects.filter(team=self.team, path="A", type="folder").first()
        folder_ab = FileSystem.objects.filter(team=self.team, path="A/B", type="folder").first()
        assert folder_a is not None
        self.assertEqual(folder_a.depth, 1)
        assert folder_ab is not None
        self.assertEqual(folder_ab.depth, 2)
        # The full path "A/B/C" should NOT be created by assure_parent_folders.
        folder_abc = FileSystem.objects.filter(team=self.team, path="A/B/C").first()
        self.assertIsNone(folder_abc)
