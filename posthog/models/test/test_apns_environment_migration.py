import base64
import importlib

from posthog.test.base import BaseTest

from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from parameterized import parameterized

from posthog.models import Team
from posthog.models.integration import Integration

migration = importlib.import_module("posthog.migrations.1362_apns_environment_integration_id")

MIGRATE_FROM = ("posthog", "1361_asyncdeletion_event_deletion_type")


def a_signing_key() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def stored_ciphertext(pk: int) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT sensitive_config FROM posthog_integration WHERE id = %s", [pk])
        return cursor.fetchone()[0]


class TestApnsEnvironmentMigration(BaseTest):
    def run_migration(self) -> None:
        executor = MigrationExecutor(connection)
        migration.normalize_apns_integrations(executor.loader.project_state(MIGRATE_FROM).apps, None)

    def an_integration(
        self, *, environment, bundle_id="com.example.app", team_id="TEAMID1234", signing_key=None, integration_id=None
    ):
        return Integration.objects.create(
            team=self.team,
            kind="apns",
            integration_id=integration_id or f"{team_id.strip()}.{bundle_id.strip()}",
            config={
                "team_id": team_id,
                "bundle_id": bundle_id,
                "key_id": "KEYID12345",
                "environment": environment,
            },
            sensitive_config={"signing_key": signing_key if signing_key is not None else a_signing_key().strip()},
        )

    def test_a_sandbox_row_frees_the_bare_id_for_the_production_row(self):
        sandbox = self.an_integration(environment="sandbox")
        production = self.an_integration(environment="production", bundle_id="com.example.other")

        self.run_migration()
        sandbox.refresh_from_db()
        production.refresh_from_db()

        assert sandbox.integration_id == "TEAMID1234.com.example.app:sandbox"
        assert production.integration_id == "TEAMID1234.com.example.other"

    def test_a_whitespace_row_takes_the_bare_id_the_sandbox_row_gave_up(self):
        sandbox = self.an_integration(environment="sandbox")
        padded = self.an_integration(
            environment="production", team_id=" TEAMID1234", integration_id=" TEAMID1234.com.example.app"
        )

        self.run_migration()
        sandbox.refresh_from_db()
        padded.refresh_from_db()

        assert sandbox.integration_id == "TEAMID1234.com.example.app:sandbox"
        assert padded.integration_id == "TEAMID1234.com.example.app"
        assert padded.config["team_id"] == "TEAMID1234"

    def test_a_row_the_current_keys_cannot_decrypt_does_not_stop_the_migration(self):
        unreadable = Fernet(base64.urlsafe_b64encode(b"x" * 32)).encrypt(b'{"signing_key": "k"}').decode()
        stranded = self.an_integration(environment="sandbox")
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE posthog_integration SET sensitive_config = to_jsonb(%s::text) WHERE id = %s",
                [unreadable, stranded.pk],
            )
        before = stored_ciphertext(stranded.pk)

        self.run_migration()
        stranded.refresh_from_db()

        assert stranded.integration_id == "TEAMID1234.com.example.app:sandbox"
        assert stored_ciphertext(stranded.pk) == before

    def test_a_key_that_needs_no_strip_keeps_its_stored_ciphertext(self):
        integration = self.an_integration(environment="sandbox")
        before = stored_ciphertext(integration.pk)

        self.run_migration()
        integration.refresh_from_db()

        assert integration.integration_id.endswith(":sandbox")
        assert stored_ciphertext(integration.pk) == before

    def test_a_padded_key_is_stripped_and_stays_usable(self):
        key = a_signing_key().strip()
        integration = self.an_integration(environment="production", signing_key=f"  {key}  ")

        self.run_migration()
        integration.refresh_from_db()

        assert integration.sensitive_config["signing_key"] == key
        serialization.load_pem_private_key(integration.sensitive_config["signing_key"].encode(), password=None)

    def test_a_config_value_that_is_not_a_string_is_skipped(self):
        integration = self.an_integration(environment="production")
        integration.config = {**integration.config, "bundle_id": 12345}
        integration.save(update_fields=["config"])

        self.run_migration()
        integration.refresh_from_db()

        assert integration.integration_id == "TEAMID1234.com.example.app"

    def test_two_rows_that_differ_only_by_whitespace_both_survive(self):
        first = self.an_integration(environment="production")
        second = self.an_integration(
            environment="production", team_id="TEAMID1234 ", integration_id="TEAMID1234.com.example.app "
        )

        self.run_migration()
        first.refresh_from_db()
        second.refresh_from_db()

        assert first.integration_id == "TEAMID1234.com.example.app"
        assert second.integration_id == "TEAMID1234.com.example.app "
        assert Integration.objects.filter(kind="apns").count() == 2

    @parameterized.expand(
        [
            ("a list", "[1, 2, 3]"),
            ("a string", '"not a mapping"'),
            ("null", "null"),
            ("a number", "42"),
        ]
    )
    def test_a_config_that_is_not_a_mapping_does_not_stop_the_migration(self, _name, raw_config):
        healthy = self.an_integration(environment="sandbox")
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO posthog_integration "
                "(team_id, kind, integration_id, config, sensitive_config, repository_cache, created_at, errors) "
                "VALUES (%s, 'apns', 'odd-shape', %s::jsonb, '{}'::jsonb, '{}'::jsonb, now(), '')",
                [self.team.id, raw_config],
            )

        self.run_migration()
        healthy.refresh_from_db()

        assert healthy.integration_id == "TEAMID1234.com.example.app:sandbox"

    def test_a_second_team_keeps_its_own_row_for_the_same_bundle(self):
        mine = self.an_integration(environment="sandbox")
        other_team = Team.objects.create(organization=self.organization, name="other")
        theirs = Integration.objects.create(
            team=other_team,
            kind="apns",
            integration_id="TEAMID1234.com.example.app",
            config={"team_id": "TEAMID1234", "bundle_id": "com.example.app", "environment": "sandbox"},
            sensitive_config={"signing_key": a_signing_key().strip()},
        )

        self.run_migration()
        mine.refresh_from_db()
        theirs.refresh_from_db()

        assert mine.integration_id == "TEAMID1234.com.example.app:sandbox"
        assert theirs.integration_id == "TEAMID1234.com.example.app:sandbox"
