from datetime import UTC, datetime
from typing import Any

from posthog.test.base import NonAtomicTestMigrations

from django.db import IntegrityError, connection

OLDER = datetime(2026, 1, 1, tzinfo=UTC)
NEWER = datetime(2026, 2, 1, tzinfo=UTC)


class RebuildColumnConfigurationIndexesMigrationTest(NonAtomicTestMigrations):
    migrate_from = "1331_messagingrecord_campaign_key_idx"
    migrate_to = "1333_rebuild_column_configuration_unique_indexes"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        User = apps.get_model("posthog", "User")
        ColumnConfiguration = apps.get_model("posthog", "ColumnConfiguration")

        org = Organization.objects.create(name="Test Organization")
        project = Project.objects.create(id=999996, organization=org, name="Test Project")
        team = Team.objects.create(organization=org, project=project, name="Test Team")
        creator = User.objects.create(email="creator@example.com", password="")

        # A cancelled concurrent build in production leaves the unique index invalid, so
        # duplicates slip in. Drop the indexes here to reproduce that unenforced state.
        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX IF EXISTS unique_user_view_name")
            cursor.execute("DROP INDEX IF EXISTS unique_team_view_name")

        def make(name: str, visibility: str, updated_at: Any, created_by: Any = None) -> Any:
            row = ColumnConfiguration.objects.create(
                team=team, context_key="ctx", columns=["a"], name=name, visibility=visibility, created_by=created_by
            )
            # updated_at is auto_now, so set it through .update() to bypass the save hook.
            ColumnConfiguration.objects.filter(pk=row.pk).update(updated_at=updated_at)
            return row.pk

        self.shared_keep = make("Shared", "shared", NEWER)
        self.shared_rename = make("Shared", "shared", OLDER)
        self.shared_untouched = make("Unique", "shared", NEWER)

        self.private_keep = make("Private", "private", NEWER, created_by=creator)
        self.private_rename = make("Private", "private", OLDER, created_by=creator)

        # Null creator rows are distinct under the partial index, so they must not be renamed.
        self.anon_a = make("Anon", "private", NEWER)
        self.anon_b = make("Anon", "private", OLDER)

        self.team_id = team.pk

    def _name(self, pk: Any) -> str:
        assert self.apps is not None
        return self.apps.get_model("posthog", "ColumnConfiguration").objects.get(pk=pk).name

    def test_dedupes_conflicts_and_rebuilds_enforcing_indexes(self) -> None:
        assert self.apps is not None
        ColumnConfiguration = self.apps.get_model("posthog", "ColumnConfiguration")

        # The most recently updated row in each conflicting group keeps its name.
        assert self._name(self.shared_keep) == "Shared"
        assert self._name(self.private_keep) == "Private"
        assert self._name(self.shared_untouched) == "Unique"

        # The older duplicate is renamed with an id fragment, so the unique build can succeed.
        assert self._name(self.shared_rename) == f"Shared ({str(self.shared_rename)[:8]})"
        assert self._name(self.private_rename) == f"Private ({str(self.private_rename)[:8]})"

        # Null-creator private rows never conflict, so both keep their name.
        assert self._name(self.anon_a) == "Anon"
        assert self._name(self.anon_b) == "Anon"

        # The rebuilt index is valid and enforcing: a fresh shared duplicate is rejected.
        with self.assertRaises(IntegrityError):
            ColumnConfiguration.objects.create(
                team_id=self.team_id, context_key="ctx", columns=["a"], name="Shared", visibility="shared"
            )
