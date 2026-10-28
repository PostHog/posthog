import json
from io import StringIO

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.management.commands.setup_local_dev import LocalDevSetup
from posthog.models import Team, User
from posthog.models.instance_setting import InstanceSetting


@override_settings(DEBUG=True, CLOUD_DEPLOYMENT=None, SITE_URL="http://localhost:8010")
class TestLocalDevReadiness(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "migrations",
                ["posthog.pending"],
                {"OIDC_RSA_PRIVATE_KEY": "configured"},
                "Run `python manage.py migrate`",
            ),
            ("oauth_key", [], {}, "Local OAuth signing is not configured"),
        ]
    )
    def test_missing_prerequisites_stop_before_account_lookup(
        self, _name: str, pending: list[str], oauth: dict[str, str], message: str
    ) -> None:
        with (
            patch("posthog.management.commands.setup_local_dev.get_pending_postgres_migrations", return_value=pending),
            override_settings(OAUTH2_PROVIDER=oauth),
            self.assertRaisesMessage(CommandError, message),
        ):
            call_command("setup_local_dev")


@override_settings(DEBUG=True, CLOUD_DEPLOYMENT=None, SITE_URL="http://localhost:8010")
class TestSetupLocalDev(APIBaseTest):
    def test_rerun_keeps_existing_account_project_password_and_token(self) -> None:
        self.user.email = "test@posthog.com"
        self.user.set_password("12345678")
        self.user.save()
        password = self.user.password
        token = self.team.api_token
        user_count = User.objects.count()
        team_count = Team.objects.count()
        outputs = []
        storage: dict[str, str] = {}

        def write(path: str, content: str, **kwargs: object) -> None:
            storage[path] = content

        with (
            patch("posthog.management.commands.setup_local_dev.get_pending_postgres_migrations", return_value=[]),
            override_settings(OBJECT_STORAGE_ENABLED=True),
            patch("posthog.storage.object_storage.read", side_effect=lambda path, **kwargs: storage.get(path)),
            patch("posthog.storage.object_storage.write", side_effect=write),
        ):
            for _ in range(2):
                output = StringIO()
                call_command("setup_local_dev", json=True, stdout=output)
                outputs.append(json.loads(output.getvalue()))
        assert outputs[0] == outputs[1]
        assert outputs[0]["user_id"] == self.user.pk
        assert outputs[0]["team_id"] == self.team.pk
        assert outputs[0]["account_created"] is False
        self.user.refresh_from_db()
        self.team.refresh_from_db()
        assert self.user.password == password
        assert self.team.api_token == token
        assert self.user.current_team_id == self.team.pk
        assert User.objects.count() == user_count
        assert Team.objects.count() == team_count

    def test_existing_demo_token_is_not_taken_from_another_project(self) -> None:
        self.user.email = "another@example.com"
        self.user.save(update_fields=["email"])
        self.team.api_token = "phc_localposthogprojecttoken"
        self.team.save(update_fields=["api_token"])
        user_count = User.objects.count()
        with (
            patch("posthog.management.commands.setup_local_dev.get_pending_postgres_migrations", return_value=[]),
            self.assertRaisesMessage(CommandError, "already belongs to another project"),
        ):
            call_command("setup_local_dev")
        self.team.refresh_from_db()
        assert self.team.api_token == "phc_localposthogprojecttoken"
        assert User.objects.count() == user_count

    @parameterized.expand(
        [
            ("failure", RuntimeError("Object storage unavailable"), CommandError),
            ("interruption", KeyboardInterrupt(), KeyboardInterrupt),
        ]
    )
    def test_incomplete_initialization_blocks_retry_without_duplicate_account(
        self, _name: str, failure: BaseException, expected_error: type[BaseException]
    ) -> None:
        original_users = User.objects.count()
        original_teams = Team.objects.count()
        with (
            patch("posthog.management.commands.setup_local_dev.get_pending_postgres_migrations", return_value=[]),
            patch("posthog.management.commands.generate_demo_data.MatrixManager.run_on_team", side_effect=failure),
        ):
            with self.assertRaises(expected_error):
                call_command("setup_local_dev", stdout=StringIO())
            incomplete_user = User.objects.get(email="test@posthog.com")
            incomplete_team = Team.objects.get(organization__members=incomplete_user)
            token = incomplete_team.api_token
            with self.assertRaisesMessage(CommandError, "generation will not run again automatically") as retry:
                call_command("setup_local_dev", stdout=StringIO())
        assert f"user {incomplete_user.pk}, project {incomplete_team.pk}" in str(retry.exception)
        assert User.objects.count() == original_users + 1
        assert Team.objects.count() == original_teams + 1
        incomplete_team.refresh_from_db()
        assert incomplete_team.api_token == token
        marker = InstanceSetting.objects.get(key=LocalDevSetup.STATE_KEY)
        assert marker.value["phase"] == "started"
        assert marker.value["user_id"] == incomplete_user.pk
        assert marker.value["team_id"] == incomplete_team.pk

    def test_another_setup_session_prevents_first_run_writes(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", [LocalDevSetup.LOCK_KEY])
        try:
            with (
                patch("posthog.management.commands.setup_local_dev.get_pending_postgres_migrations", return_value=[]),
                self.assertRaisesMessage(CommandError, "Another local setup is running"),
            ):
                call_command("setup_local_dev", stdout=StringIO())
            assert not User.objects.filter(email="test@posthog.com").exists()
            assert not InstanceSetting.objects.filter(key=LocalDevSetup.STATE_KEY).exists()
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [LocalDevSetup.LOCK_KEY])
