from django.test import TestCase

from posthog.models import Organization, Team, User
from posthog.models.file_system.file_system import (
    DEFAULT_SURFACE,
    FileSystem,
    create_or_update_file,
    delete_file,
    escape_path,
    join_path,
    split_path,
    surface_q,
)
from posthog.models.file_system.unfiled_file_saver import save_unfiled_files

from products.dashboards.backend.models.dashboard import Dashboard
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.models.insight import Insight


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
        ff = FeatureFlag.objects.create(team=self.team, key="Beta Feature", created_by=self.user)
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
        FeatureFlag.objects.create(team=self.team, key="Active Flag", created_by=self.user, deleted=False)
        FeatureFlag.objects.create(team=self.team, key="Deleted Flag", created_by=self.user, deleted=True)
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
        ff = FeatureFlag.objects.create(team=self.team, key="Some Flag", created_by=self.user)
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
        FeatureFlag.objects.create(team=self.team, key="Beta Feature", created_by=self.user)
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

        FeatureFlag.objects.create(team=self.team, key="Duplicate Name", created_by=self.user)
        self.assertEqual(FileSystem.objects.filter(path="Unfiled/Feature Flags/Duplicate Name").count(), 2)

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
        FeatureFlag.objects.create(team=self.team, key="A Flag", created_by=self.user)
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


class TestFileSystemSurface(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("surface@posthog.com", "testpassword", first_name="Sue")
        self.organization = Organization.objects.create(name="Surface Org")
        self.team = Team.objects.create(name="Surface Team", organization=self.organization)

    def test_surface_q_default_matches_null_and_web(self):
        legacy = FileSystem.objects.create(team=self.team, path="Legacy", type="insight", ref="1", surface=None)
        web = FileSystem.objects.create(team=self.team, path="Web", type="insight", ref="2", surface="web")
        FileSystem.objects.create(team=self.team, path="Desktop", type="insight", ref="3", surface="desktop")

        web_ids = set(FileSystem.objects.filter(surface_q(DEFAULT_SURFACE)).values_list("id", flat=True))
        self.assertEqual(web_ids, {legacy.id, web.id})

        desktop_paths = set(FileSystem.objects.filter(surface_q("desktop")).values_list("path", flat=True))
        self.assertEqual(desktop_paths, {"Desktop"})

    def test_create_or_update_file_isolates_surfaces(self):
        create_or_update_file(
            team=self.team, base_folder="Web", name="Same", file_type="insight", ref="42", href="", meta={}
        )
        create_or_update_file(
            team=self.team,
            base_folder="Desktop",
            name="Same",
            file_type="insight",
            ref="42",
            href="",
            meta={},
            surface="desktop",
        )

        rows = FileSystem.objects.filter(type="insight", ref="42").order_by("surface")
        self.assertEqual(rows.count(), 2)
        self.assertEqual({r.surface for r in rows}, {"web", "desktop"})

    def test_create_or_update_file_web_updates_legacy_null_row(self):
        legacy = FileSystem.objects.create(
            team=self.team, path="Old/Name", type="insight", ref="7", surface=None, shortcut=False
        )

        create_or_update_file(
            team=self.team, base_folder="Old", name="New Name", file_type="insight", ref="7", href="", meta={}
        )

        legacy.refresh_from_db()
        # The web write matched and renamed the legacy NULL row instead of creating a second one.
        self.assertEqual(FileSystem.objects.filter(type="insight", ref="7").count(), 1)
        self.assertEqual(legacy.path, "Old/New Name")

    def test_delete_file_is_scoped_to_surface(self):
        create_or_update_file(
            team=self.team, base_folder="Web", name="Keep", file_type="insight", ref="9", href="", meta={}
        )
        create_or_update_file(
            team=self.team,
            base_folder="Desktop",
            name="Keep",
            file_type="insight",
            ref="9",
            href="",
            meta={},
            surface="desktop",
        )

        delete_file(team=self.team, file_type="insight", ref="9")

        remaining = FileSystem.objects.filter(type="insight", ref="9")
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().surface, "desktop")  # type: ignore

    def test_mixin_models_default_to_web_surface(self):
        FeatureFlag.objects.create(team=self.team, key="A Flag", created_by=self.user)
        entry = FileSystem.objects.get(type="feature_flag")
        self.assertEqual(entry.surface, DEFAULT_SURFACE)

    def test_unfiled_saver_only_sweeps_requested_surface(self):
        FeatureFlag.objects.create(team=self.team, key="Beta", created_by=self.user)
        FileSystem.objects.all().delete()

        # No models are registered for the desktop surface, so nothing is swept into it.
        self.assertEqual(save_unfiled_files(self.team, self.user, surface="desktop"), [])
        self.assertEqual(FileSystem.objects.count(), 0)

        created = save_unfiled_files(self.team, self.user)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].surface, DEFAULT_SURFACE)

    def test_get_file_system_unfiled_scopes_exclusion_to_surface(self):
        # Creating the flag files it into the web tree via the post_save signal.
        FeatureFlag.objects.create(team=self.team, key="Gamma", created_by=self.user)

        # The web exclusion sees it as already filed, so it is not unfiled for web...
        self.assertEqual(FeatureFlag.get_file_system_unfiled(self.team, surface="web").count(), 0)
        # ...but it is still unfiled for desktop, whose tree doesn't contain it.
        self.assertEqual(FeatureFlag.get_file_system_unfiled(self.team, surface="desktop").count(), 1)
