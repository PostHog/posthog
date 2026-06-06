from django.test import TestCase

from posthog.models import FileSystem, Organization, Team, User
from posthog.models.file_system.file_system_view_log import FileSystemViewLog

from products.dashboards.backend.models.dashboard import Dashboard
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.models.insight import Insight


class TestFileSystemSyncMixin(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user("test@posthog.com", "testpassword", "Tester")

    def test_feature_flag_create_triggers_file_creation(self):
        """
        When a FeatureFlag is created, if should_delete=False (deleted=False),
        a new FileSystem entry should be created via the Mixin's signals.
        """
        # Create a FeatureFlag
        flag = FeatureFlag.objects.create(team=self.team, key="My Feature", deleted=False, created_by=self.user)
        # The Mixin's post_save signal should create a FileSystem row
        fs_entry = FileSystem.objects.filter(team=self.team, type="feature_flag", ref=str(flag.id)).first()
        assert fs_entry is not None
        self.assertEqual(fs_entry.path, "Unfiled/Feature Flags/My Feature")
        self.assertEqual(fs_entry.created_by, self.user)
        self.assertEqual(fs_entry.shortcut, False)

    def test_feature_flag_delete_field_triggers_file_removal_on_save(self):
        """
        If we update the FeatureFlag so that `deleted=True` and call save(),
        the Mixin's post_save signal should remove the FileSystem entry,
        because DSL config says: `should_delete: lambda instance: instance.deleted`.
        """
        flag = FeatureFlag.objects.create(team=self.team, key="My Feature", deleted=False, created_by=self.user)
        self.assertEqual(FileSystem.objects.count(), 1)  # It's created

        # Now mark as deleted
        flag.deleted = True
        flag.save()

        # The Mixin's post_save should remove the corresponding FileSystem entry
        fs_entry = FileSystem.objects.filter(team=self.team, type="feature_flag", ref=str(flag.id)).first()
        assert fs_entry is None
        self.assertEqual(FileSystem.objects.count(), 0)

    def test_feature_flag_physical_delete_triggers_file_removal(self):
        """
        On a real delete (post_delete), the Mixin should remove the FileSystem entry.
        """
        flag = FeatureFlag.objects.create(team=self.team, key="Temp Feature", deleted=False, created_by=self.user)
        self.assertEqual(FileSystem.objects.count(), 1)

        flag_id = flag.id
        flag.delete()  # triggers post_delete
        fs_entry = FileSystem.objects.filter(team=self.team, type="feature_flag", ref=str(flag_id)).first()
        assert fs_entry is None
        self.assertEqual(FileSystem.objects.count(), 0)

    def test_feature_flag_name_update_renames_file_system_path(self):
        """
        If a FeatureFlag's name changes, we verify that the FileSystem path
        also updates (depending on your DSL or create_or_update_file logic).
        """
        flag = FeatureFlag.objects.create(team=self.team, key="Old Key", deleted=False, created_by=self.user)
        fs_entry = FileSystem.objects.get(team=self.team, type="feature_flag", ref=str(flag.id))
        self.assertEqual(fs_entry.path, "Unfiled/Feature Flags/Old Key")

        # Update name
        flag.key = "New Key"
        flag.save()

        fs_entry.refresh_from_db()
        # Confirm the path changed to the new name
        self.assertEqual(fs_entry.path, "Unfiled/Feature Flags/New Key")

    def test_experiment_always_saved(self):
        """
        The DSL for 'experiment' says `should_delete: lambda instance: False`.
        So we expect the FileSystem entry to always exist, ignoring any 'deleted' field.
        (If your model doesn't have a 'deleted' field, this just ensures it's created.)
        """
        ff = FeatureFlag.objects.create(team=self.team, key="Beta Feature", created_by=self.user)
        exp = Experiment.objects.create(team=self.team, name="Exp #1", created_by=self.user, feature_flag=ff)
        fs_entry = FileSystem.objects.filter(team=self.team, type="experiment", ref=str(exp.id)).first()
        assert fs_entry is not None
        self.assertEqual(fs_entry.path, "Unfiled/Experiments/Exp #1")
        self.assertEqual(fs_entry.shortcut, False)

        # If we manually add a field `deleted=True` (if it existed),
        # the DSL says ignore. We'll simulate that:
        exp.name = "Exp #1 Updated"
        exp.save()

        # Should remain in the FileSystem
        fs_entry.refresh_from_db()
        self.assertEqual(fs_entry.path, "Unfiled/Experiments/Exp #1 Updated")

    def test_insight_deleted_or_unsaved_removes_entry(self):
        """
        The DSL for 'insight' says: `should_delete: lambda instance: instance.deleted or not instance.saved`.
        So if Insight.deleted == True OR Insight.saved == False => remove from FileSystem.
        """
        insight = Insight.objects.create(
            team=self.team, name="My Insight", saved=True, deleted=False, created_by=self.user
        )
        fs_entry = FileSystem.objects.filter(team=self.team, type="insight", ref=insight.short_id).first()
        assert fs_entry is not None
        self.assertEqual(fs_entry.path, "Unfiled/Insights/My Insight")

        # Mark as not saved
        insight.saved = False
        insight.save()
        self.assertFalse(Insight.objects.get(id=insight.id).saved)
        fs_entry = FileSystem.objects.filter(team=self.team, type="insight", ref=insight.short_id).first()
        assert fs_entry is None

        # Now mark as saved again
        insight.saved = True
        insight.deleted = False
        insight.save()
        # Because we updated from "deleted or not saved" => false, we should get a new entry
        new_fs_entry = FileSystem.objects.filter(team=self.team, type="insight", ref=insight.short_id).first()
        assert new_fs_entry is not None

        # Mark as deleted
        insight.deleted = True
        insight.save()
        fs_entry2 = FileSystem.objects.filter(team=self.team, type="insight", ref=insight.short_id).first()
        assert fs_entry2 is None

    def test_dashboard_delete_field_removal(self):
        """
        By default the DSL might not exist for 'dashboard', but let's assume if we had:
        'should_delete': lambda instance: instance.deleted or instance.creation_mode == "template"
        We'll confirm that toggling `deleted=True` removes it from FileSystem.
        """
        dash = Dashboard.objects.create(team=self.team, name="Main Dash", created_by=self.user, deleted=False)
        fs_entry = FileSystem.objects.filter(team=self.team, type="dashboard", ref=str(dash.id)).first()
        assert fs_entry is not None
        self.assertEqual(fs_entry.path, "Unfiled/Dashboards/Main Dash")

        dash.deleted = True
        dash.save()
        fs_entry_after = FileSystem.objects.filter(team=self.team, type="dashboard", ref=str(dash.id)).first()
        assert fs_entry_after is None

    def test_notebook_basic_lifecycle(self):
        """
        If Notebook is created with deleted=False, it gets a file system entry,
        then physically deleting it removes the entry.
        """
        note = Notebook.objects.create(team=self.team, title="My Notebook", deleted=False, created_by=self.user)
        fs_entry = FileSystem.objects.filter(team=self.team, type="notebook", ref=str(note.short_id)).first()
        assert fs_entry is not None
        self.assertEqual(fs_entry.path, "Unfiled/Notebooks/My Notebook")

        # Physical delete
        note_id = note.short_id
        note.delete()
        fs_entry2 = FileSystem.objects.filter(team=self.team, type="notebook", ref=str(note_id)).first()
        assert fs_entry2 is None

    def test_notebook_internal_visibility(self):
        note = Notebook.objects.create(
            team=self.team, title="My Notebook", created_by=self.user, visibility=Notebook.Visibility.INTERNAL
        )
        fs_entry = FileSystem.objects.filter(team=self.team, type="notebook", ref=str(note.id)).first()

        assert fs_entry is None, "Should not create file system entry for internal notebook"
        assert note.get_file_system_representation().should_delete, "Internal notebook should be set for deletion"

    def test_notebook_internal_visibility_delete_existing_entry(self):
        note = Notebook.objects.create(
            team=self.team, title="My Notebook", created_by=self.user, visibility=Notebook.Visibility.INTERNAL
        )
        fs_entry = FileSystem.objects.create(
            team=self.team,
            path=f"{note._get_assigned_folder('Unfiled/Notebooks')}/My Notebook",
            depth=2,
            type="notebook",
            ref=str(note.short_id),
            href=f"/notebooks/{note.short_id}",
            meta={"created_at": str(note.created_at)},
            shortcut=False,
            created_by_id=self.user.id,
            created_at=note.created_at,
        )
        fs_entry_id = fs_entry.id

        note.save()

        assert FileSystem.objects.filter(id=fs_entry_id).exists() is False, (
            "Existing entries for internal notebooks should be deleted"
        )

    def test_file_system_delete_clears_view_logs(self):
        """
        When a FileSystem row is removed (e.g. because the underlying insight was soft-deleted),
        the matching FileSystemViewLog rows must also disappear so the Recents sidebar can't
        surface a dead reference.
        """
        insight = Insight.objects.create(team=self.team, name="My Insight", saved=True, created_by=self.user)
        fs_entry = FileSystem.objects.get(team=self.team, type="insight", ref=insight.short_id)
        FileSystemViewLog.objects.create(team=self.team, user=self.user, type="insight", ref=insight.short_id)
        self.assertEqual(FileSystemViewLog.objects.count(), 1)

        # Soft-deleting the insight runs the post_save signal, which removes the FileSystem entry
        insight.deleted = True
        insight.save()

        assert not FileSystem.objects.filter(id=fs_entry.id).exists()
        self.assertEqual(FileSystemViewLog.objects.count(), 0)

    def test_file_system_view_logs_survive_when_legacy_null_shortcut_row_remains(self):
        """
        Legacy FileSystem rows can have shortcut=NULL (the field is nullable and the Recents
        query treats NULL as canonical). Deleting one canonical row while another canonical
        row with shortcut=NULL still exists must not clear the view logs.
        """
        insight = Insight.objects.create(team=self.team, name="My Insight", saved=True, created_by=self.user)
        FileSystemViewLog.objects.create(team=self.team, user=self.user, type="insight", ref=insight.short_id)

        legacy_row = FileSystem.objects.create(
            team=self.team,
            path=f"Legacy/{insight.name}",
            depth=2,
            type="insight",
            ref=insight.short_id,
            href=f"/insights/{insight.short_id}",
            shortcut=None,
            created_by=self.user,
        )

        canonical = FileSystem.objects.get(team=self.team, type="insight", ref=insight.short_id, shortcut=False)
        canonical.delete()

        assert FileSystem.objects.filter(id=legacy_row.id).exists()
        self.assertEqual(FileSystemViewLog.objects.count(), 1)

    def test_file_system_view_logs_survive_shortcut_deletion(self):
        """
        Shortcuts share (type, ref) with their canonical file. Deleting a shortcut must not
        clear view logs — they should follow the canonical row's lifecycle.
        """
        insight = Insight.objects.create(team=self.team, name="My Insight", saved=True, created_by=self.user)
        FileSystemViewLog.objects.create(team=self.team, user=self.user, type="insight", ref=insight.short_id)

        shortcut = FileSystem.objects.create(
            team=self.team,
            path=f"Shortcuts/{insight.name}",
            depth=2,
            type="insight",
            ref=insight.short_id,
            href=f"/insights/{insight.short_id}",
            shortcut=True,
            created_by=self.user,
        )
        shortcut.delete()

        self.assertEqual(FileSystemViewLog.objects.count(), 1)
