from django.test import TestCase
from posthog.models import FeatureFlag, Experiment, Dashboard, Insight, Notebook, Team, User, Organization
from posthog.models.file_system.file_system import (
    FileSystem,
    escape_path,
    join_path,
    split_path,
)
from posthog.models.file_system.unfiled_file_saver import save_unfiled_files


class TestFileSystemModel(TestCase):
    def setUp(self):
        # Create a Team and a User
        self.user = User.objects.create_user("test@posthog.com", "testpassword", first_name="Bob")
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(name="Test Team", organization=self.organization)

    def test_save_unfiled_files_with_no_objects(self):
        """
        If no FeatureFlags, Experiments, Dashboards, Insights, or Notebooks exist,
        save_unfiled_files should create no FileSystem rows.
        """
        created = save_unfiled_files(self.team, self.user)
        self.assertEqual(len(created), 0)
        self.assertEqual(FileSystem.objects.count(), 0)

    def test_save_unfiled_files_with_various_objects(self):
        """
        Test that FeatureFlags, Experiments, Dashboards, Insights, and Notebooks
        are created as FileSystem objects in the DB by save_unfiled_files.
        """
        # Create some objects
        ff = FeatureFlag.objects.create(team=self.team, name="Beta Feature", created_by=self.user, key="flaggy")
        Experiment.objects.create(team=self.team, name="Experiment #1", created_by=self.user, feature_flag=ff)
        Dashboard.objects.create(team=self.team, name="Main Dashboard", created_by=self.user)
        Insight.objects.create(team=self.team, name="Traffic Insight", created_by=self.user, saved=True)
        Notebook.objects.create(team=self.team, title="Data Exploration", created_by=self.user)
        FileSystem.objects.all().delete()

        # Call the saver
        created = save_unfiled_files(self.team, self.user)
        self.assertEqual(len(created), 5)  # One FileSystem row per object

        # Verify DB state
        self.assertEqual(FileSystem.objects.count(), 5)
        types_in_db = set(FileSystem.objects.values_list("type", flat=True))
        self.assertIn("feature_flag", types_in_db)
        self.assertIn("experiment", types_in_db)
        self.assertIn("dashboard", types_in_db)
        self.assertIn("insight", types_in_db)
        self.assertIn("notebook", types_in_db)

    def test_save_unfiled_files_excludes_deleted_flags(self):
        """
        FeatureFlags with deleted=True should NOT create FileSystem rows.
        """
        FeatureFlag.objects.create(
            team=self.team, name="Active Flag", created_by=self.user, deleted=False, key="flaggy1"
        )
        FeatureFlag.objects.create(
            team=self.team, name="Deleted Flag", created_by=self.user, deleted=True, key="flaggy2"
        )
        FileSystem.objects.all().delete()
        created = save_unfiled_files(self.team, self.user)
        self.assertEqual(len(created), 1)
        self.assertEqual(FileSystem.objects.count(), 1)
        self.assertEqual(FileSystem.objects.first().path, "Unfiled/Feature Flags/Active Flag")  # type: ignore

    def test_save_unfiled_files_excludes_deleted_insights(self):
        """
        Insights with deleted=True should NOT create FileSystem rows.
        """
        Insight.objects.create(team=self.team, name="Active Insight", created_by=self.user, deleted=False, saved=True)
        Insight.objects.create(team=self.team, name="Deleted Insight", created_by=self.user, deleted=True, saved=True)
        FileSystem.objects.all().delete()
        created = save_unfiled_files(self.team, self.user)
        self.assertEqual(len(created), 1)
        self.assertEqual(FileSystem.objects.count(), 1)
        self.assertEqual(FileSystem.objects.first().path, "Unfiled/Insights/Active Insight")  # type: ignore

    def test_save_unfiled_files_includes_all_experiments(self):
        """
        There's no 'deleted=False' field in Experiment, so all
        experiments should create FileSystem rows.
        """
        ff = FeatureFlag.objects.create(team=self.team, name="Some Flag", created_by=self.user, key="flaggy1")
        Experiment.objects.create(team=self.team, name="Experiment #1", created_by=self.user, feature_flag=ff)
        FileSystem.objects.all().delete()
        created = save_unfiled_files(self.team, self.user)
        self.assertEqual(len(created), 2)  # 1 FeatureFlag, 1 Experiment
        exp_item = FileSystem.objects.filter(type="experiment").first()
        assert exp_item.path is not None  # type: ignore
        self.assertEqual(exp_item.path, "Unfiled/Experiments/Experiment #1")  # type: ignore

    def test_save_unfiled_files_does_not_duplicate_existing(self):
        """
        If save_unfiled_files is called multiple times, existing items in FileSystem
        should NOT be recreated.
        """
        FeatureFlag.objects.create(team=self.team, name="Beta Feature", created_by=self.user, key="flaggy")
        FileSystem.objects.all().delete()

        first_created = save_unfiled_files(self.team, self.user)
        self.assertEqual(len(first_created), 1)
        self.assertEqual(FileSystem.objects.count(), 1)

        second_created = save_unfiled_files(self.team, self.user)
        self.assertEqual(len(second_created), 0)
        self.assertEqual(FileSystem.objects.count(), 1)

        self.assertEqual(FileSystem.objects.first().path, "Unfiled/Feature Flags/Beta Feature")  # type: ignore

    def test_no_naming_collision_with_existing_db_object(self):
        """
        We already have a FileSystem row named 'Unfiled/Feature Flags/Duplicate Name', we can make another
        """
        FileSystem.objects.create(
            team=self.team,
            path="Unfiled/Feature Flags/Duplicate Name",
            type="feature_flag",
            ref="999",
            created_by=self.user,
        )

        FeatureFlag.objects.create(team=self.team, name="Duplicate Name", created_by=self.user)
        self.assertEqual(FileSystem.objects.filter(path="Unfiled/Feature Flags/Duplicate Name").count(), 2)

    def test_naming_collisions_among_multiple_new_items_same_run(self):
        """
        If multiple new FeatureFlags are created with the same name, they should
        be saved with unique paths in FileSystem.
        """
        FeatureFlag.objects.create(team=self.team, name="Same Name", key="name-1", created_by=self.user)
        FeatureFlag.objects.create(team=self.team, name="Same Name", key="name-2", created_by=self.user)
        FileSystem.objects.all().delete()
        created = save_unfiled_files(self.team, self.user)

        self.assertEqual(len(created), 2)
        paths = [obj.path for obj in created]
        self.assertEqual(
            paths,
            [
                "Unfiled/Feature Flags/Same Name",
                "Unfiled/Feature Flags/Same Name",
            ],
        )

    def test_split_path(self):
        self.assertEqual(split_path("a/b"), ["a", "b"])
        self.assertEqual(split_path("a\\/b/c"), ["a/b", "c"])
        self.assertEqual(split_path("a\\/b\\\\/c"), ["a/b\\", "c"])
        self.assertEqual(split_path("a\n\t/b"), ["a\n\t", "b"])
        self.assertEqual(split_path("a"), ["a"])
        self.assertEqual(split_path(""), [])
        self.assertEqual(split_path("///"), [])  # all empty segments
        self.assertEqual(split_path("a////b"), ["a", "b"])

    def test_escape_path(self):
        self.assertEqual(escape_path(""), "")
        self.assertEqual(escape_path("abc"), "abc")
        self.assertEqual(escape_path("a/b"), "a\\/b")
        self.assertEqual(escape_path("a\\b"), "a\\\\b")
        self.assertEqual(escape_path("a/b\\c"), "a\\/b\\\\c")
        self.assertEqual(escape_path("\\/"), "\\\\\\/")  # each slash/backslash gets escaped
        self.assertEqual(escape_path("Hello, World!"), "Hello, World!")
        self.assertEqual(escape_path("Hello/World"), "Hello\\/World")
        self.assertEqual(escape_path("Hello: World"), "Hello: World")
        self.assertEqual(escape_path("Hello\\World"), "Hello\\\\World")
        self.assertEqual(escape_path("Hello\\/World"), "Hello\\\\\\/World")

    def test_join_path(self):
        # Normal usage
        self.assertEqual(join_path(["a", "b"]), "a/b")
        self.assertEqual(join_path(["one", "two", "three"]), "one/two/three")
        # Check that forward slashes and backslashes get escaped within segments
        self.assertEqual(join_path(["a/b", "c\\d"]), "a\\/b/c\\\\d")
        # Edge case: empty list
        self.assertEqual(join_path([]), "")

    # Example test for save_unfiled_files with a specific file_type
    def test_save_unfiled_files_specific_type(self):
        """
        If we pass a specific file_type (e.g., FEATURE_FLAG) then only that type should be saved.
        """
        # Create a FeatureFlag and a Dashboard
        FeatureFlag.objects.create(team=self.team, name="A Flag", created_by=self.user, key="flaggy")
        Dashboard.objects.create(team=self.team, name="A Dashboard", created_by=self.user)
        FileSystem.objects.all().delete()

        # Call with file_type=FEATURE_FLAG
        created_flags = save_unfiled_files(self.team, self.user, file_type="feature_flag")
        self.assertEqual(len(created_flags), 1)
        self.assertEqual(created_flags[0].type, "feature_flag")
        self.assertEqual(created_flags[0].path, "Unfiled/Feature Flags/A Flag")

        # Ensure dashboard is still unfiled
        self.assertEqual(FileSystem.objects.count(), 1)

        # Now explicitly save dashboards
        created_dashboards = save_unfiled_files(self.team, self.user, file_type="dashboard")
        self.assertEqual(len(created_dashboards), 1)
        self.assertEqual(created_dashboards[0].type, "dashboard")
        self.assertEqual(created_dashboards[0].path, "Unfiled/Dashboards/A Dashboard")

        # Confirm total in DB
        self.assertEqual(FileSystem.objects.count(), 2)
