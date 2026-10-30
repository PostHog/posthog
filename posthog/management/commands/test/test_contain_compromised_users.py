import json
from datetime import timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from unittest.mock import patch

from django.contrib.admin.models import LogEntry
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.api.authentication import password_reset_token_generator
from posthog.models import User
from posthog.session.models import Session


@override_settings(CLOUD_DEPLOYMENT="US")
class TestContainCompromisedUsers(TestCase):
    def setUp(self) -> None:
        self.operator = User.objects.create(email="operator@example.com", is_staff=True)
        self.target = User.objects.create_user(
            email="target@example.com", password="old-example-password", first_name="Target"
        )
        self.other = User.objects.create_user(
            email="other@example.com", password="other-example-password", first_name="Other"
        )
        for user in (self.target, self.other):
            Session.objects.create(
                session_key=str(uuid4()),
                session_data="",
                user_id=user.pk,
                expire_date=timezone.now() + timedelta(days=1),
            )
        self.output = StringIO()

    def _run(self, *arguments: str) -> None:
        call_command(
            "contain_compromised_users",
            "--operator-uuid",
            str(self.operator.uuid),
            "--reason",
            "security-review-example",
            *arguments,
            stdout=self.output,
        )

    def test_dry_run_file_input_is_non_mutating_and_deduplicated(self) -> None:
        original_password = self.target.password
        with TemporaryDirectory() as directory:
            path = Path(directory) / "users.txt"
            path.write_text(f"{self.target.uuid}\n\n{self.target.uuid}\n")
            self._run("--user-uuids-file", str(path), "--dry-run")

        self.target.refresh_from_db()
        self.assertEqual(self.target.password, original_password)
        self.assertEqual(Session.objects.filter(user_id=self.target.pk).count(), 1)
        self.assertFalse(LogEntry.objects.exists())
        self.assertIn("Selected accounts: 1", self.output.getvalue())
        self.assertIn("DRY RUN", self.output.getvalue())

    def test_execution_disables_only_selected_passwords_and_sessions_with_audit(self) -> None:
        old_reset_token = password_reset_token_generator.make_token(self.target)
        self._run("--user-uuids", str(self.target.uuid))

        self.target.refresh_from_db()
        self.other.refresh_from_db()
        self.assertFalse(self.target.has_usable_password())
        self.assertFalse(self.target.check_password("old-example-password"))
        self.assertTrue(self.target.is_active)
        self.assertFalse(Session.objects.filter(user_id=self.target.pk).exists())
        self.assertTrue(self.other.check_password("other-example-password"))
        self.assertTrue(Session.objects.filter(user_id=self.other.pk).exists())
        self.assertFalse(password_reset_token_generator.check_token(self.target, old_reset_token))
        self.assertTrue(
            password_reset_token_generator.check_token(
                self.target, password_reset_token_generator.make_token(self.target)
            )
        )
        entry = LogEntry.objects.get(object_id=str(self.target.pk))
        self.assertEqual(entry.user_id, self.operator.pk)
        self.assertEqual(json.loads(entry.change_message)["web_sessions_revoked"], 1)
        self.assertEqual(json.loads(entry.change_message)["reason"], "security-review-example")
        self.assertNotIn("old-example-password", entry.change_message)

    @parameterized.expand([("missing",), ("malformed",), ("self",), ("operator",), ("reason",)])
    def test_invalid_input_aborts_before_any_writes(self, case: str) -> None:
        targets = [str(self.target.uuid)]
        extra = []
        if case == "missing":
            targets.append(str(uuid4()))
        elif case == "malformed":
            targets.append("target@example.com")
        elif case == "self":
            targets.append(str(self.operator.uuid))
        elif case == "operator":
            extra = ["--operator-uuid", str(self.other.uuid)]
        elif case == "reason":
            extra = ["--reason", " "]

        with self.assertRaises(CommandError):
            self._run("--user-uuids", *targets, *extra)

        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("old-example-password"))
        self.assertTrue(Session.objects.filter(user_id=self.target.pk).exists())
        self.assertFalse(LogEntry.objects.exists())

    def test_audit_failure_rolls_back_password_and_session_changes(self) -> None:
        with patch(
            "posthog.management.commands.contain_compromised_users.LogEntry.objects.create", side_effect=RuntimeError
        ):
            with self.assertRaises(RuntimeError):
                self._run("--user-uuids", str(self.target.uuid))

        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("old-example-password"))
        self.assertTrue(Session.objects.filter(user_id=self.target.pk).exists())
        self.assertNotIn("Completed:", self.output.getvalue())
