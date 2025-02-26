from django.test import TestCase
from posthog.models import FeatureFlag, Experiment, Dashboard, Insight, Notebook, Team, User, Organization
from posthog.models.file_system import FileSystem, save_unfiled_files, FileSystemType, sanitize_filename


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

        # Call the saver
        created = save_unfiled_files(self.team, self.user)
        self.assertEqual(len(created), 5)  # One FileSystem row per object

        # Verify DB state
        self.assertEqual(FileSystem.objects.count(), 5)
        types_in_db = set(FileSystem.objects.values_list("type", flat=True))
        self.assertIn(FileSystemType.FEATURE_FLAG, types_in_db)
        self.assertIn(FileSystemType.EXPERIMENT, types_in_db)
        self.assertIn(FileSystemType.DASHBOARD, types_in_db)
        self.assertIn(FileSystemType.INSIGHT, types_in_db)
        self.assertIn(FileSystemType.NOTEBOOK, types_in_db)

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
        created = save_unfiled_files(self.team, self.user)
        self.assertEqual(len(created), 2)  # 1 FeatureFlag, 1 Experiment
        exp_item = FileSystem.objects.filter(type=FileSystemType.EXPERIMENT).first()
        assert exp_item.path is not None  # type: ignore
        self.assertEqual(exp_item.path, "Unfiled/Experiments/Experiment #1")  # type: ignore

    def test_save_unfiled_files_does_not_duplicate_existing(self):
        """
        If save_unfiled_files is called multiple times, existing items in FileSystem
        should NOT be recreated.
        """
        FeatureFlag.objects.create(team=self.team, name="Beta Feature", created_by=self.user, key="flaggy")

        first_created = save_unfiled_files(self.team, self.user)
        self.assertEqual(len(first_created), 1)
        self.assertEqual(FileSystem.objects.count(), 1)

        second_created = save_unfiled_files(self.team, self.user)
        self.assertEqual(len(second_created), 0)
        self.assertEqual(FileSystem.objects.count(), 1)

        self.assertEqual(FileSystem.objects.first().path, "Unfiled/Feature Flags/Beta Feature")  # type: ignore

    def test_naming_collision_with_existing_db_object(self):
        """
        If we already have a FileSystem row named 'Unfiled/Feature Flags/Duplicate Name',
        then creating a new FeatureFlag with that same name should result in a FileSystem
        path of '... (1)'.
        """
        FileSystem.objects.create(
            team=self.team,
            path="Unfiled/Feature Flags/Duplicate Name",
            type=FileSystemType.FEATURE_FLAG,
            ref="999",
            created_by=self.user,
        )

        FeatureFlag.objects.create(team=self.team, name="Duplicate Name", created_by=self.user)
        created = save_unfiled_files(self.team, self.user)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].path, "Unfiled/Feature Flags/Duplicate Name (1)")
        self.assertTrue(FileSystem.objects.filter(path="Unfiled/Feature Flags/Duplicate Name (1)").exists())

    def test_naming_collisions_among_multiple_new_items_same_run(self):
        """
        If multiple new FeatureFlags are created with the same name, they should
        be saved with unique paths in FileSystem.
        """
        FeatureFlag.objects.create(team=self.team, name="Same Name", key="name-1", created_by=self.user)
        FeatureFlag.objects.create(team=self.team, name="Same Name", key="name-2", created_by=self.user)
        created = save_unfiled_files(self.team, self.user)

        self.assertEqual(len(created), 2)
        paths = [obj.path for obj in created]
        self.assertEqual(
            paths,
            [
                "Unfiled/Feature Flags/Same Name",
                "Unfiled/Feature Flags/Same Name (1)",
            ],
        )

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("Hello, World!"), "Hello, World!")
        self.assertEqual(sanitize_filename("Hello/World"), "Hello\\/World")
        self.assertEqual(sanitize_filename("Hello: World"), "Hello: World")
        self.assertEqual(sanitize_filename("Hello\\World"), "Hello\\\\World")
        self.assertEqual(sanitize_filename("Hello\\/World"), "Hello\\\\\\/World")
