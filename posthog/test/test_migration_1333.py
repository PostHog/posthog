from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from posthog.test.base import NonAtomicTestMigrations

from django.db import IntegrityError, connection

OLDER = datetime(2026, 1, 1, tzinfo=UTC)
NEWER = datetime(2026, 2, 1, tzinfo=UTC)

# Three ids sharing the first 8 characters, as UUIDv7s minted in one ~65s window do.
# Renaming with only that shared prefix would give the two older rows the same name.
WINDOW_KEEP_ID = UUID("01a05cf4-1457-76f7-8000-000000000001")
WINDOW_RENAME_A_ID = UUID("01a05cf4-1457-74b7-8000-000000000002")
WINDOW_RENAME_B_ID = UUID("01a05cf4-1457-7437-8000-000000000003")


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

        def make(name: str, visibility: str, updated_at: Any, created_by: Any = None, pk: Any = None) -> Any:
            fields: dict[str, Any] = {
                "team": team,
                "context_key": "ctx",
                "columns": ["a"],
                "name": name,
                "visibility": visibility,
                "created_by": created_by,
            }
            if pk is not None:
                fields["id"] = pk
            row = ColumnConfiguration.objects.create(**fields)
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

        # A group of three whose ids share an 8-char prefix: both older rows are renamed, so a
        # prefix-only suffix would collide and 1333's unique build would fail.
        self.window_keep = make("Windowed", "shared", NEWER, pk=WINDOW_KEEP_ID)
        self.window_rename_a = make("Windowed", "shared", OLDER, pk=WINDOW_RENAME_A_ID)
        self.window_rename_b = make("Windowed", "shared", OLDER, pk=WINDOW_RENAME_B_ID)

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

        # The older duplicate is renamed with its full id, so the unique build can succeed.
        assert self._name(self.shared_rename) == f"Shared ({self.shared_rename})"
        assert self._name(self.private_rename) == f"Private ({self.private_rename})"

        # Both older rows in the shared-prefix group keep distinct names because each suffix is
        # the row's full id, not the prefix they have in common.
        assert self._name(self.window_keep) == "Windowed"
        assert self._name(self.window_rename_a) == f"Windowed ({self.window_rename_a})"
        assert self._name(self.window_rename_b) == f"Windowed ({self.window_rename_b})"

        # Null-creator private rows never conflict, so both keep their name.
        assert self._name(self.anon_a) == "Anon"
        assert self._name(self.anon_b) == "Anon"

        # The rebuilt index is valid and enforcing: a fresh shared duplicate is rejected.
        with self.assertRaises(IntegrityError):
            ColumnConfiguration.objects.create(
                team_id=self.team_id, context_key="ctx", columns=["a"], name="Shared", visibility="shared"
            )
