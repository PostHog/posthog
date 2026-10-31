import json
from contextlib import contextmanager, redirect_stdout
from datetime import datetime
from io import StringIO
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, connection
from django.utils import timezone

from posthog.health import get_pending_postgres_migrations
from posthog.local_demo import require_local_development
from posthog.management.commands.generate_demo_data import DEMO_PROJECT_API_TOKEN
from posthog.models import Team, User
from posthog.models.instance_setting import InstanceSetting

if TYPE_CHECKING:
    from argparse import ArgumentParser
    from collections.abc import Iterator


class LocalDevSetup:
    STATE_KEY = "local_dev_setup:v1"
    LOCK_KEY = 5784945249743062358

    @staticmethod
    @contextmanager
    def initialization_lock() -> "Iterator[None]":
        lock_connection = connection.copy()
        try:
            with lock_connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [LocalDevSetup.LOCK_KEY])
                acquired = cursor.fetchone()[0]
            if not acquired:
                raise CommandError(
                    "Another local setup is running. Wait for it to finish, then run setup_local_dev again."
                )
            try:
                yield
            finally:
                with lock_connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [LocalDevSetup.LOCK_KEY])
        finally:
            lock_connection.close()

    @staticmethod
    def record_owned_account(marker: InstanceSetting) -> None:
        state = marker.value
        started_at = datetime.fromisoformat(state["started_at"])
        user = User.objects.filter(email__iexact="test@posthog.com", date_joined__gte=started_at).first()
        if user is not None:
            candidates = Team.objects.filter(created_at__gte=started_at, organization__members=user, is_demo=True)
            if state.get("fixed_token", True):
                candidates = candidates.filter(api_token=DEMO_PROJECT_API_TOKEN)
            team = candidates.first() if candidates.count() == 1 else None
            if team is not None:
                state.update(user_id=user.pk, team_id=team.pk)
        marker.raw_value = json.dumps(state)
        marker.save(update_fields=["raw_value"])

    @staticmethod
    def incomplete_error(marker: InstanceSetting) -> CommandError:
        state = marker.value
        identities = (
            f"user {state['user_id']}, project {state['team_id']}"
            if state.get("user_id") is not None and state.get("team_id") is not None
            else "an account/project that could not be identified safely"
        )
        return CommandError(
            f"Local demo initialization did not finish ({identities}). "
            "No data was reset and generation will not run again automatically. "
            "Make ClickHouse, ingestion, persons storage, and object storage ready; inspect the server logs. "
            "Manually repair or remove only this incomplete setup's resources, then clear the "
            f"InstanceSetting marker '{LocalDevSetup.STATE_KEY}' before retrying setup_local_dev. "
            "See 'Prepare the usual local test account' in developing-locally.md for recovery."
        )

    @staticmethod
    def check_environment() -> None:
        try:
            require_local_development()
        except ValueError as error:
            raise CommandError(str(error)) from error
        try:
            pending = get_pending_postgres_migrations()
        except OperationalError as error:
            raise CommandError(
                "Postgres is unavailable. Start the local services, then run this command again."
            ) from error
        if pending:
            raise CommandError(
                f"{len(pending)} unapplied Postgres migration(s), including {pending[0]}. "
                "Run `python manage.py migrate` before local setup."
            )
        if not settings.OAUTH2_PROVIDER.get("OIDC_RSA_PRIVATE_KEY"):
            raise CommandError(
                "Local OAuth signing is not configured. Set OIDC_RSA_PRIVATE_KEY in the local development "
                "environment, restart the backend, then run setup_local_dev again. Keep the private key out of source control."
            )

    @staticmethod
    def run() -> dict[str, object]:
        LocalDevSetup.check_environment()
        with LocalDevSetup.initialization_lock():
            return LocalDevSetup.setup_locked()

    @staticmethod
    def setup_locked() -> dict[str, object]:
        marker = InstanceSetting.objects.filter(key=LocalDevSetup.STATE_KEY).first()
        if marker is not None and marker.value.get("phase") != "complete":
            LocalDevSetup.record_owned_account(marker)
            raise LocalDevSetup.incomplete_error(marker)
        user = User.objects.filter(email__iexact="test@posthog.com").first()
        created = user is None
        if user is None:
            if Team.objects.filter(api_token=DEMO_PROJECT_API_TOKEN).exists():
                raise CommandError(
                    "The local demo project token already belongs to another project. "
                    "Keep that project and choose an existing account instead of creating a demo account."
                )
            marker, _ = InstanceSetting.objects.update_or_create(
                key=LocalDevSetup.STATE_KEY,
                defaults={
                    "raw_value": json.dumps(
                        {
                            "phase": "started",
                            "started_at": timezone.now().isoformat(),
                            "fixed_token": bool(settings.DEBUG and not settings.TEST),
                        }
                    )
                },
            )
            try:
                with redirect_stdout(StringIO()):
                    call_command(
                        "generate_demo_data",
                        n_clusters=20,
                        days_past=120,
                        days_future=30,
                        skip_materialization=True,
                        skip_flag_sync=True,
                        say_on_complete=False,
                        stdout=StringIO(),
                    )
                LocalDevSetup.record_owned_account(marker)
                user = User.objects.filter(email__iexact="test@posthog.com").first()
                if (
                    user is None
                    or user.current_team_id is None
                    or marker.value.get("user_id") != user.pk
                    or marker.value.get("team_id") != user.current_team_id
                ):
                    raise CommandError("The generator did not finish selecting the new demo account's project.")
            except Exception as error:
                LocalDevSetup.record_owned_account(marker)
                raise LocalDevSetup.incomplete_error(marker) from error
            marker.raw_value = json.dumps({**marker.value, "phase": "complete"})
            marker.save(update_fields=["raw_value"])
        if user is None or user.current_team_id is None:
            raise CommandError("The test account has no selected project. Select a project in the web app, then retry.")
        team = user.current_team
        if team is None or not user.teams.filter(pk=team.pk).exists():
            raise CommandError(
                "The selected project is not accessible to the test account. Select an accessible project."
            )
        if not user.is_active or not user.check_password("12345678"):
            raise CommandError(
                "The existing test account cannot use the default local password. "
                "Its password was preserved; use your existing sign-in details."
            )
        call_command("setup_tasks_oauth", stdout=StringIO())
        seeded = StringIO()
        call_command("seed_local_inbox_data", team_id=team.pk, user_id=user.pk, json=True, stdout=seeded)
        result: dict[str, object] = json.loads(seeded.getvalue())
        result["account_created"] = created
        return result


class Command(BaseCommand):
    help = "Prepare the usual local test account, OAuth callbacks, and inbox data without resetting existing data"

    def add_arguments(self, parser: "ArgumentParser") -> None:
        parser.add_argument("--json", action="store_true", help="Print selected account, project, and seeded data IDs")

    def handle(self, *args: object, **options: object) -> None:
        result = LocalDevSetup.run()
        if options["json"]:
            self.stdout.write(json.dumps(result))
        else:
            self.stdout.write(
                f"Local account ready: user {result['user_id']}, project {result['team_id']}. "
                "Run `python manage.py check_local_dev` to check authenticated API access."
            )
