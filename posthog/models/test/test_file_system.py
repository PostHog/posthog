from django.test import TestCase
from posthog.models import FeatureFlag, Experiment, Dashboard, Insight, Notebook, Team, User, Organization
from posthog.models.file_system import FileSystem, get_unfiled_files, FileSystemType
from posthog.models.utils import uuid7


class TestFileSystemModel(TestCase):
    def setUp(self):
        # Create a Team and a User (simplest approach for model tests)
        self.user = User.objects.create_user("test@posthog.com", "testpassword", first_name="Bob")
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(name="Test Team", organization=self.organization)

    def test_get_unfiled_files_with_no_objects(self):
        """
        If no FeatureFlags, Experiments, Dashboards, Insights, or Notebooks exist,
        get_unfiled_files should return an empty list.
        """
        unfiled = get_unfiled_files(self.team, self.user)
        self.assertEqual(len(unfiled), 0)

    def test_get_unfiled_files_with_various_objects(self):
        """
        Test that FeatureFlags, Experiments, Dashboards, Insights, and Notebooks
        appear as ephemeral FileSystem objects in get_unfiled_files.
        """
        # Create some objects
        ff = FeatureFlag.objects.create(team=self.team, name="Beta Feature", created_by=self.user, key="flaggy")
        Experiment.objects.create(team=self.team, name="Experiment #1", created_by=self.user, feature_flag=ff)
        Dashboard.objects.create(team=self.team, name="Main Dashboard", created_by=self.user)
        Insight.objects.create(team=self.team, name="Traffic Insight", created_by=self.user)
        Notebook.objects.create(team=self.team, title="Data Exploration", created_by=self.user)

        unfiled = get_unfiled_files(self.team, self.user)
        # We expect 5 ephemeral items
        self.assertEqual(len(unfiled), 5)

        # Check that each type is present
        types = {item.type for item in unfiled}
        self.assertIn(FileSystemType.FEATURE_FLAG, types)
        self.assertIn(FileSystemType.EXPERIMENT, types)
        self.assertIn(FileSystemType.DASHBOARD, types)
        self.assertIn(FileSystemType.INSIGHT, types)
        self.assertIn(FileSystemType.NOTEBOOK, types)

        # Check a sample item matches expected data
        ff_item = next(item for item in unfiled if item.type == FileSystemType.FEATURE_FLAG)
        self.assertEqual(ff_item.path, f"Unfiled/Feature Flags/{ff.name}")
        self.assertEqual(ff_item.ref, str(ff.id))
        self.assertEqual(ff_item.href, f"/feature_flags/{ff.id}")
        # Not saved to DB, so no actual FileSystem row with pk=ff_item.id

    def test_get_unfiled_files_excludes_deleted_flags(self):
        """
        FeatureFlags with deleted=True should NOT appear as unfiled.
        """
        FeatureFlag.objects.create(
            team=self.team, name="Active Flag", created_by=self.user, deleted=False, key="flaggy1"
        )
        FeatureFlag.objects.create(
            team=self.team, name="Deleted Flag", created_by=self.user, deleted=True, key="flaggy2"
        )
        unfiled = get_unfiled_files(self.team, self.user)
        # Only the Active Flag is returned
        self.assertEqual(len(unfiled), 1)
        self.assertEqual(unfiled[0].path, "Unfiled/Feature Flags/Active Flag")

    def test_get_unfiled_files_excludes_deleted_insights(self):
        """
        Insights with deleted=True should NOT appear as unfiled.
        """
        Insight.objects.create(team=self.team, name="Active Insight", created_by=self.user, deleted=False)
        Insight.objects.create(team=self.team, name="Deleted Insight", created_by=self.user, deleted=True)
        unfiled = get_unfiled_files(self.team, self.user)
        # Only the active insight is returned
        self.assertEqual(len(unfiled), 1)
        self.assertEqual(unfiled[0].path, "Unfiled/Insights/Active Insight")

    def test_get_unfiled_files_includes_all_experiments(self):
        """
        There's no 'deleted=False' in Experiment, so all
        experiments (for the team) should appear in the unfiled list.
        """
        flag = FeatureFlag.objects.create(
            team=self.team, name="Active Flag", created_by=self.user, deleted=False, key="flaggy1"
        )
        Experiment.objects.create(team=self.team, name="Experiment #1", created_by=self.user, feature_flag=flag)
        unfiled = get_unfiled_files(self.team, self.user)
        names = {item.path for item in unfiled if item.type == FileSystemType.EXPERIMENT}
        self.assertEqual(names, {"Unfiled/Experiments/Experiment #1"})

    def test_file_system_db_objects_are_separate_from_unfiled_results(self):
        """
        Creating an actual FileSystem DB row doesn't remove that object
        from the ephemeral unfiled list. The unfiled items are
        still returned if they exist in the FeatureFlag, Experiment, etc. tables.
        """
        # Let's create a real FileSystem object referencing a random 'ref'
        file_obj = FileSystem.objects.create(
            team=self.team,
            id=uuid7(),
            path="Custom/My Dashboard",
            type=FileSystemType.DASHBOARD,
            ref="9999",
            href="/dashboard/9999",
            created_by=self.user,
        )

        # Also create a real Dashboard row to see in unfiled
        dash = Dashboard.objects.create(team=self.team, name="Real Dashboard", created_by=self.user)
        unfiled = get_unfiled_files(self.team, self.user)

        # We do see the ephemeral item for the Dashboard we created
        dash_item = next(item for item in unfiled if item.type == FileSystemType.DASHBOARD)
        self.assertEqual(dash_item.ref, str(dash.id))
        self.assertEqual(dash_item.path, f"Unfiled/Dashboards/{dash.name}")

        # Meanwhile, our actual DB-based FileSystem item is unrelated:
        self.assertTrue(FileSystem.objects.filter(pk=file_obj.pk).exists())
        # We expect just 1 ephemeral unfiled item for the real Dashboard
        self.assertEqual(sum(i.type == FileSystemType.DASHBOARD for i in unfiled), 1)

        # The ephemeral object is not the same ID as the DB FileSystem object
        self.assertNotEqual(dash_item.id, str(file_obj.id))
