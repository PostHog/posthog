from typing import Any

from posthog.test.base import BaseTest

from django.db import connection
from django.db.migrations.loader import MigrationLoader

import structlog.testing

from posthog.models.project_secret_api_key import find_project_secret_api_key
from posthog.models.utils import hash_key_value

PRIMARY = "phs_backfill_test_primary_token"
BACKUP = "phs_backfill_test_backup_token"
COLLIDING = "phs_backfill_test_label_collision_token"
LEAK_REVOKED = "phs_backfill_test_leak_revoked_token"
DOUBLE_COLLIDING = "phs_backfill_test_double_collision_token"


class TestBackfillSecretTokensToPsak(BaseTest):
    migrate_from = "1393_revokedteamsecrettoken"
    migrate_to = "1394_backfill_secret_tokens_to_psak"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Team = apps.get_model("posthog", "Team")
        ProjectSecretAPIKey = apps.get_model("posthog", "ProjectSecretAPIKey")

        Team.objects.filter(id=self.team.id).update(secret_api_token=PRIMARY, secret_api_token_backup=BACKUP)
        # The primary already has a row (a rerun, or a key the customer made themselves):
        # the backfill must not duplicate it or touch its label.
        ProjectSecretAPIKey.objects.create(
            team_id=self.team.id,
            label="Customer-made key",
            secure_value=hash_key_value(PRIMARY),
            scopes=["feature_flag:read"],
        )

        self.collision_team_id = Team.objects.create(
            organization_id=self.organization.id,
            project_id=self.team.project_id,
            name="label collision",
            secret_api_token=COLLIDING,
        ).id
        ProjectSecretAPIKey.objects.create(
            team_id=self.collision_team_id,
            label="Migrated legacy secret API key",
            secure_value=hash_key_value("phs_backfill_test_unrelated_token"),
            scopes=["feature_flag:read"],
        )

        self.double_collision_team_id = Team.objects.create(
            organization_id=self.organization.id,
            project_id=self.team.project_id,
            name="double label collision",
            secret_api_token=DOUBLE_COLLIDING,
        ).id
        for label in (
            "Migrated legacy secret API key",
            f"Migrated legacy secret API key {hash_key_value(DOUBLE_COLLIDING)[-8:]}",
        ):
            ProjectSecretAPIKey.objects.create(
                team_id=self.double_collision_team_id,
                label=label,
                secure_value=hash_key_value(f"phs_backfill_test_unrelated_{label[-4:]}"),
                scopes=["feature_flag:read"],
            )

        self.leaked_team_id = Team.objects.create(
            organization_id=self.organization.id,
            project_id=self.team.project_id,
            name="leak revoked",
            secret_api_token=LEAK_REVOKED,
        ).id
        apps.get_model("posthog", "RevokedTeamSecretToken").objects.create(
            team_id=self.leaked_team_id, secure_value=hash_key_value(LEAK_REVOKED)
        )

        self.empty_team_id = Team.objects.create(
            organization_id=self.organization.id,
            project_id=self.team.project_id,
            name="no legacy token",
            secret_api_token="",
        ).id

        # Fresh teams start with NULL, and exclude(field="") keeps NULL rows: only the
        # isnull exclude stops hash_key_value(None) from aborting the deploy.
        self.null_team_id = Team.objects.create(
            organization_id=self.organization.id,
            project_id=self.team.project_id,
            name="null legacy token",
            secret_api_token=None,
        ).id

    def setUp(self) -> None:
        super().setUp()
        loader = MigrationLoader(connection)
        state = loader.project_state([("posthog", self.migrate_from)])
        self.setUpBeforeMigration(state.apps)
        migration = loader.get_migration("posthog", self.migrate_to)
        with structlog.testing.capture_logs() as logs, connection.schema_editor(atomic=False) as schema_editor:
            self.apps = migration.apply(state, schema_editor).apps
        self.logs = logs

    def test_backfill_covers_backup_dedup_label_collision_and_empty(self) -> None:
        assert self.apps is not None
        ProjectSecretAPIKey = self.apps.get_model("posthog", "ProjectSecretAPIKey")

        # The backup gets its own row, resolvable like any PSAK.
        migrated = find_project_secret_api_key(BACKUP)
        assert migrated is not None
        assert migrated.team_id == self.team.id
        assert migrated.scopes == ["feature_flag:read", "support_ticket:read"]
        assert migrated.label == "Migrated legacy key (backup)"
        assert migrated.mask_value

        # The primary's pre-existing row is left alone: no duplicate, label untouched.
        primary_rows = ProjectSecretAPIKey.objects.filter(secure_value=hash_key_value(PRIMARY))
        assert [row.label for row in primary_rows] == ["Customer-made key"]

        # A taken base label falls back to a suffixed one instead of violating (team, label).
        collision_row = find_project_secret_api_key(COLLIDING)
        assert collision_row is not None
        assert collision_row.label == f"Migrated legacy secret API key {hash_key_value(COLLIDING)[-8:]}"

        # Base and fallback labels both taken: the row is skipped, not an IntegrityError,
        # and the warning operators grep for before the column drop names the team.
        assert find_project_secret_api_key(DOUBLE_COLLIDING) is None
        assert ProjectSecretAPIKey.objects.filter(team_id=self.double_collision_team_id).count() == 2
        skip_logs = [log for log in self.logs if log.get("event") == "backfill_label_collision_skipped"]
        assert [log["team_id"] for log in skip_logs] == [self.double_collision_team_id]

        # A leak-revoked hash stays dead: no fresh mirror row for a still-leaked token.
        assert find_project_secret_api_key(LEAK_REVOKED) is None
        assert not ProjectSecretAPIKey.objects.filter(team_id=self.leaked_team_id).exists()

        # A team with an empty or NULL legacy token gets nothing.
        assert not ProjectSecretAPIKey.objects.filter(team_id=self.empty_team_id).exists()
        assert not ProjectSecretAPIKey.objects.filter(team_id=self.null_team_id).exists()
