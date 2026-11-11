from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from copy import deepcopy
from io import StringIO
from typing import TYPE_CHECKING, Any, cast

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction

from parameterized import parameterized

from posthog.integrations import IntegrationManager
from posthog.models.team import Team

from products.batch_exports.backend.logic.credentials_backfill import (
    CredentialBackfillOutcome,
    backfill_batch_export_credentials,
    verify_batch_export_credentials,
)
from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination

if TYPE_CHECKING:
    from posthog.integrations import IntegrationRecord

SECRET = "obviously-fake-backfill-secret-do-not-print"
AWS_PAIR = {"aws_access_key_id": "fake-access-key", "aws_secret_access_key": SECRET}
INLINE: dict[str, object] = {
    "host": "fake.example.com",
    "user": "fake-user",
    "password": SECRET,
    "port": "5439",
    "database": "fake-database",
    **AWS_PAIR,
}


class TestBackfillBatchExportCredentials(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.sync = self.enterContext(
            patch("products.batch_exports.backend.logic.credentials_backfill.sync_batch_export")
        )
        for boundary in (
            "socket.getaddrinfo",
            "requests.sessions.Session.request",
            "httpx.Client.send",
            "httpx.AsyncClient.send",
            "botocore.client.BaseClient._make_api_call",
        ):
            self.enterContext(patch(boundary, side_effect=AssertionError("Network access is disabled")))

    def _create(
        self,
        *,
        config: object | None = None,
        name: str = "Fake export",
        integration_id: int | None = None,
        team_id: int | None = None,
        deleted: bool = False,
        paused: bool = False,
    ) -> BatchExport:
        destination = BatchExportDestination.objects.create(
            type="Redshift",
            config=deepcopy(INLINE if config is None else config),
            integration_id=integration_id,
        )
        export = BatchExport.objects.create(
            team_id=self.team.id if team_id is None else team_id,
            name=name,
            destination=destination,
            interval="hour",
            deleted=deleted,
            paused=paused,
        )
        destination.refresh_from_db()
        return export

    def _run(
        self,
        *,
        execute: bool = True,
        sync_schedules: bool = True,
        team_ids: Sequence[int] = (),
        destination_types: Sequence[str] = (),
        limit: int | None = None,
        batch_size: int = 200,
        on_batch: Callable[[int], None] | None = None,
    ) -> Counter[CredentialBackfillOutcome]:
        with self.captureOnCommitCallbacks(execute=True):
            counts = backfill_batch_export_credentials(
                execute=execute,
                sync_schedules=sync_schedules,
                team_ids=team_ids,
                destination_types=destination_types,
                limit=limit,
                batch_size=batch_size,
                on_batch=on_batch,
            )
        return counts

    def _existing_config(self) -> dict[str, Any]:
        return {
            "host": "fake.example.com",
            "port": 5439,
            "user": "fake-user",
            "ssl_mode": "require",
            "ssl_root_cert": None,
        }

    def _existing(
        self,
        export: BatchExport,
        *,
        config_overrides: dict[str, Any] | None = None,
        sensitive_config: dict[str, Any] | None = None,
    ) -> IntegrationRecord:
        return IntegrationManager.aws_redshift.credentials.create(
            export.team_id,
            external_id=f"{export.team_id}-fake.example.com-5439-fake-user",
            config={**self._existing_config(), **(config_overrides or {})},
            sensitive_config=sensitive_config or {"password": SECRET},
        )

    def _stored_config(self, export: BatchExport) -> bytes:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT config::text FROM posthog_batchexportdestination WHERE id = %s",
                [export.destination_id],
            )
            row = cursor.fetchone()
        assert row is not None
        return row[0].encode("utf-8")

    def test_links_connection_and_keeps_inline_values(self) -> None:
        export = self._create(
            config={
                **INLINE,
                "copy_inputs": {
                    "bucket_credentials": AWS_PAIR,
                    "authorization": {
                        "aws_access_key_id": "fake-second-key",
                        "aws_secret_access_key": "gAAAAAfake-undecryptable-ciphertext",
                    },
                },
            }
        )
        original = deepcopy(export.destination.config)
        original_stored_config = self._stored_config(export)
        stdout = StringIO()

        with self.captureOnCommitCallbacks(execute=True):
            call_command("backfill_batch_export_credentials", "--execute", stdout=stdout)

        self.assertIn("Redshift integration_created: 1", stdout.getvalue())

        export.destination.refresh_from_db()
        row = IntegrationManager.aws_redshift.credentials.get(
            self.team.id, cast(int, export.destination.integration_id)
        )
        self.assertEqual(row.kind, "aws-redshift")
        self.assertEqual(
            row.config,
            {
                "host": "fake.example.com",
                "port": 5439,
                "user": "fake-user",
                "ssl_mode": "require",
                "ssl_root_cert": None,
            },
        )
        self.assertEqual(row.sensitive_config, {"password": SECRET})
        self.assertEqual(export.destination.config, original)
        self.assertEqual(self._stored_config(export), original_stored_config)
        self.assertEqual(export.destination.config["copy_inputs"], original["copy_inputs"])
        self.assertEqual(export.destination.config["user"], INLINE["user"])
        self.assertEqual(export.destination.config["password"], SECRET)
        self.assertEqual(IntegrationManager.aws_s3.credentials.list(self.team.id), [])
        self.sync.assert_called_once_with(export, created=False)
        self.assertEqual(self.sync.call_args.args[0].destination.integration_id, row.id)
        self.assertEqual(self._run(), {CredentialBackfillOutcome(destination_type="Redshift", outcome="unchanged"): 1})
        self.assertEqual(len(IntegrationManager.aws_redshift.credentials.list(self.team.id)), 1)
        self.sync.assert_called_once()

    def test_preview_writes_nothing(self) -> None:
        export = self._create(config={**INLINE, "copy_inputs": {"authorization": AWS_PAIR}})
        original = deepcopy(export.destination.config)

        self.assertEqual(
            self._run(execute=False),
            {CredentialBackfillOutcome(destination_type="Redshift", outcome="integration_created"): 1},
        )

        export.destination.refresh_from_db()
        self.assertIsNone(export.destination.integration_id)
        self.assertEqual(export.destination.config, original)
        self.assertEqual(IntegrationManager.aws_redshift.credentials.list(self.team.id), [])
        self.assertEqual(IntegrationManager.aws_s3.credentials.list(self.team.id), [])
        self.sync.assert_not_called()

    def test_matching_integration_is_reused(self) -> None:
        export = self._create()
        row = self._existing(export)

        self.assertEqual(
            self._run(), {CredentialBackfillOutcome(destination_type="Redshift", outcome="integration_reused"): 1}
        )

        export.destination.refresh_from_db()
        self.assertEqual(export.destination.integration_id, row.id)
        self.assertEqual(export.destination.config["password"], SECRET)
        self.assertEqual(len(IntegrationManager.aws_redshift.credentials.list(self.team.id)), 1)

    def test_existing_link_keeps_inline_values(self) -> None:
        export = self._create(config={**INLINE, "copy_inputs": {"authorization": AWS_PAIR}})
        row = self._existing(export)
        export.destination.integration_id = row.id
        export.destination.save(update_fields=["integration_id"])
        original = deepcopy(export.destination.config)

        self.assertEqual(self._run(), {CredentialBackfillOutcome(destination_type="Redshift", outcome="unchanged"): 1})

        export.destination.refresh_from_db()
        self.assertEqual(export.destination.config, original)
        self.assertEqual(verify_batch_export_credentials(), {})
        stdout = StringIO()
        call_command("backfill_batch_export_credentials", "--verify", stdout=stdout)
        self.assertIn("Total outcomes: 0", stdout.getvalue())
        self.sync.assert_not_called()

    @parameterized.expand(
        [
            ("different_password", {"sensitive_config": {"password": "fake-conflicting-secret"}}),
            ("different_ssl_mode", {"config_overrides": {"ssl_mode": "disable"}}),
        ]
    )
    def test_conflict_gets_its_own_integration(self, _name: str, overrides: dict[str, Any]) -> None:
        export = self._create()
        other = self._create(name="Fake second export")
        shared = self._existing(export, **overrides)
        original = deepcopy(export.destination.config)
        created = CredentialBackfillOutcome(destination_type="Redshift", outcome="integration_created_separate")

        self.assertEqual(
            verify_batch_export_credentials(),
            {CredentialBackfillOutcome(destination_type="Redshift", outcome="needs_integration"): 2},
        )
        self.assertEqual(self._run(), {created: 2})

        export.destination.refresh_from_db()
        other.destination.refresh_from_db()
        ids = {export.destination.integration_id, other.destination.integration_id}
        self.assertEqual(len(ids), 2)
        self.assertNotIn(shared.id, ids)
        self.assertNotIn(None, ids)
        for item in (export, other):
            row = IntegrationManager.aws_redshift.credentials.get(
                self.team.id, cast(int, item.destination.integration_id)
            )
            found = IntegrationManager.aws_redshift.credentials.find(
                self.team.id, external_id=f"{self.team.id}-fake.example.com-5439-fake-user-{item.destination.id}"
            )
            self.assertIsNotNone(found)
            self.assertEqual(cast("IntegrationRecord", found).id, row.id)
            self.assertEqual(row.sensitive_config, {"password": SECRET})
            self.assertEqual(row.config["ssl_mode"], "require")
        self.assertEqual(export.destination.config, original)
        after = IntegrationManager.aws_redshift.credentials.get(self.team.id, shared.id)
        self.assertEqual((after.config, after.sensitive_config), (shared.config, shared.sensitive_config))
        self.assertEqual(len(IntegrationManager.aws_redshift.credentials.list(self.team.id)), 3)

        self.assertEqual(self._run(), {CredentialBackfillOutcome(destination_type="Redshift", outcome="unchanged"): 2})
        self.assertEqual(len(IntegrationManager.aws_redshift.credentials.list(self.team.id)), 3)
        self.assertEqual(verify_batch_export_credentials(), {})

    def test_conflict_reuses_matching_destination_integration(self) -> None:
        export = self._create()
        self._existing(export, sensitive_config={"password": "fake-conflicting-secret"})
        own = IntegrationManager.aws_redshift.credentials.create(
            export.team_id,
            external_id=f"{export.team_id}-fake.example.com-5439-fake-user-{export.destination_id}",
            config=self._existing_config(),
            sensitive_config={"password": SECRET},
        )

        self.assertEqual(
            self._run(), {CredentialBackfillOutcome(destination_type="Redshift", outcome="integration_reused"): 1}
        )

        export.destination.refresh_from_db()
        self.assertEqual(export.destination.integration_id, own.id)
        self.assertEqual(len(IntegrationManager.aws_redshift.credentials.list(self.team.id)), 2)

    def test_conflict_with_mismatched_destination_integration_is_skipped(self) -> None:
        export = self._create()
        self._existing(export, sensitive_config={"password": "fake-conflicting-secret"})
        IntegrationManager.aws_redshift.credentials.create(
            export.team_id,
            external_id=f"{export.team_id}-fake.example.com-5439-fake-user-{export.destination_id}",
            config=self._existing_config(),
            sensitive_config={"password": "fake-other-secret"},
        )

        self.assertEqual(
            self._run(), {CredentialBackfillOutcome(destination_type="Redshift", outcome="skipped_conflict"): 1}
        )

        export.destination.refresh_from_db()
        self.assertIsNone(export.destination.integration_id)
        self.assertEqual(len(IntegrationManager.aws_redshift.credentials.list(self.team.id)), 2)
        self.sync.assert_not_called()

    def test_non_conflicting_destination_still_reuses_shared_integration(self) -> None:
        conflicting = self._create()
        self._existing(conflicting, sensitive_config={"password": "fake-conflicting-secret"})
        matching = self._create(name="Fake matching export", config={**INLINE, "user": "fake-other-user"})
        shared = IntegrationManager.aws_redshift.credentials.create(
            matching.team_id,
            external_id=f"{matching.team_id}-fake.example.com-5439-fake-other-user",
            config={**self._existing_config(), "user": "fake-other-user"},
            sensitive_config={"password": SECRET},
        )

        counts = self._run()

        self.assertEqual(
            counts[CredentialBackfillOutcome(destination_type="Redshift", outcome="integration_reused")], 1
        )
        matching.destination.refresh_from_db()
        conflicting.destination.refresh_from_db()
        self.assertEqual(matching.destination.integration_id, shared.id)
        self.assertNotEqual(conflicting.destination.integration_id, shared.id)
        self.assertIsNotNone(conflicting.destination.integration_id)

    @parameterized.expand(
        [
            ("password", ""),
            ("host", " "),
            ("user", None),
            ("port", "not-an-integer"),
            ("port", "1.5"),
            ("port", True),
        ]
    )
    def test_incomplete_connection_is_not_written(self, key: str, value: object) -> None:
        export = self._create(config={**INLINE, key: value})
        original = deepcopy(export.destination.config)

        self.assertEqual(
            self._run(), {CredentialBackfillOutcome(destination_type="Redshift", outcome="skipped_incomplete"): 1}
        )

        export.destination.refresh_from_db()
        self.assertIsNone(export.destination.integration_id)
        self.assertEqual(export.destination.config, original)
        self.assertEqual(IntegrationManager.aws_redshift.credentials.list(self.team.id), [])
        self.sync.assert_not_called()

    @parameterized.expand([("fake-unreadable",), (["fake-unreadable"],)])
    def test_unreadable_config_is_not_written(self, config: object) -> None:
        export = self._create(config=config)

        self.assertEqual(
            self._run(), {CredentialBackfillOutcome(destination_type="Redshift", outcome="skipped_unreadable"): 1}
        )
        self.assertEqual(
            verify_batch_export_credentials(),
            {CredentialBackfillOutcome(destination_type="Redshift", outcome="skipped_unreadable"): 1},
        )
        export.destination.refresh_from_db()
        self.assertEqual(export.destination.config, config)
        self.sync.assert_not_called()

    def test_missing_port_uses_redshift_default(self) -> None:
        config = {key: value for key, value in INLINE.items() if key != "port"}
        export = self._create(config=config)

        self._run()

        export.destination.refresh_from_db()
        row = IntegrationManager.aws_redshift.credentials.get(
            self.team.id, cast(int, export.destination.integration_id)
        )
        self.assertEqual(row.config["port"], 5439)
        self.assertEqual(export.destination.config, config)

    @parameterized.expand([(False, False, True), (False, True, True), (True, False, False)])
    def test_only_live_exports_are_changed(self, deleted: bool, paused: bool, expected_change: bool) -> None:
        export = self._create(deleted=deleted, paused=paused)

        counts = self._run()

        export.destination.refresh_from_db()
        self.assertEqual(export.destination.integration_id is not None, expected_change)
        self.assertEqual(bool(counts), expected_change)
        self.assertEqual(self.sync.call_count, int(expected_change))
        if expected_change:
            self.assertEqual(self.sync.call_args.args[0].paused, paused)

    @parameterized.expand([("team",), ("type",), ("limit",), ("zero",)])
    def test_command_filters(self, variant: str) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Fake other team")
        exports = [self._create(), self._create(team_id=other_team.id), self._create()]
        args = {
            "team": ["--team-id", str(self.team.id)],
            "type": ["--type", "Redshift"],
            "limit": ["--limit", "1"],
            "zero": ["--limit", "0"],
        }[variant]

        call_command(
            "backfill_batch_export_credentials",
            "--execute",
            "--no-sync-schedules",
            "--batch-size",
            "1",
            *args,
            stdout=StringIO(),
        )

        changed: list[BatchExport] = []
        for export in exports:
            export.destination.refresh_from_db()
            if export.destination.integration_id is not None:
                changed.append(export)
        expected = {
            "team": [exports[0], exports[2]],
            "type": exports,
            "limit": [min(exports, key=lambda export: export.destination.id)],
            "zero": [],
        }[variant]
        self.assertEqual({export.id for export in changed}, {export.id for export in expected})
        self.sync.assert_not_called()

    def test_batch_callback_and_limit(self) -> None:
        for index in range(3):
            self._create(name=f"Fake export {index}")
        on_batch = Mock()

        self._run(batch_size=1, limit=2, on_batch=on_batch)

        self.assertEqual([call.args[0] for call in on_batch.call_args_list], [1, 1])
        self.assertEqual(BatchExportDestination.objects.filter(integration_id__isnull=False).count(), 2)

    @parameterized.expand([(False, False), (True, False), (True, True)])
    def test_schedule_sync_failure_and_disable(self, sync_schedules: bool, fails: bool) -> None:
        export = self._create(paused=True)
        if fails:
            self.sync.side_effect = RuntimeError(SECRET)
        with patch("products.batch_exports.backend.logic.credentials_backfill.logger") as logger:
            counts = self._run(sync_schedules=sync_schedules)
        export.destination.refresh_from_db()
        self.assertIsNotNone(export.destination.integration_id)
        self.assertEqual(self.sync.call_count, int(sync_schedules))
        self.assertEqual(
            counts[CredentialBackfillOutcome(destination_type="Redshift", outcome="schedule_sync_failed")], int(fails)
        )
        if fails:
            logger.warning.assert_called_once_with(
                "batch_export_credentials.schedule_sync_failed",
                export_id=str(export.id),
                exception_type="RuntimeError",
            )
        else:
            logger.warning.assert_not_called()

    def test_verify_before_and_after_backfill(self) -> None:
        self._create()
        stdout = StringIO()

        with self.assertRaises(CommandError):
            call_command("backfill_batch_export_credentials", "--verify", stdout=stdout)

        self.assertIn("needs_integration: 1", stdout.getvalue())
        self.sync.assert_not_called()
        self._run()
        stdout = StringIO()
        call_command("backfill_batch_export_credentials", "--verify", stdout=stdout)
        self.assertIn("Total outcomes: 0", stdout.getvalue())

    @parameterized.expand([([],), (["--execute", "--no-sync-schedules"],), (["--verify"],)])
    def test_command_never_prints_credentials(self, args: list[str]) -> None:
        self._create()
        stdout, stderr = StringIO(), StringIO()

        try:
            call_command("backfill_batch_export_credentials", *args, stdout=stdout, stderr=stderr)
        except CommandError as error:
            self.assertEqual(args, ["--verify"])
            self.assertNotIn(SECRET, str(error))

        self.assertNotIn(SECRET, stdout.getvalue() + stderr.getvalue())
        self.assertIn("Total outcomes:", stdout.getvalue())
        if not args:
            self.assertIn("Dry run: nothing was written", stdout.getvalue())

    @parameterized.expand(
        [
            (["--execute", "--verify"],),
            (["--batch-size", "0"],),
            (["--limit", "-1"],),
            (["--type", "fake-unsupported"],),
        ]
    )
    def test_command_rejects_invalid_options(self, args: list[str]) -> None:
        with self.assertRaises(CommandError):
            call_command("backfill_batch_export_credentials", *args, stdout=StringIO(), stderr=StringIO())

    def test_rollback_does_not_sync_schedule(self) -> None:
        export = self._create()

        with self.captureOnCommitCallbacks(execute=True), self.assertRaisesRegex(RuntimeError, "Fake rollback"):
            with transaction.atomic():
                backfill_batch_export_credentials(execute=True)
                self.sync.assert_not_called()
                raise RuntimeError("Fake rollback")

        export.destination.refresh_from_db()
        self.assertIsNone(export.destination.integration_id)
        self.assertEqual(IntegrationManager.aws_redshift.credentials.list(self.team.id), [])
        self.sync.assert_not_called()

    def test_verify_incomplete_rows_remain_visible(self) -> None:
        self._create(config={})

        counts = verify_batch_export_credentials()

        self.assertEqual(
            counts[CredentialBackfillOutcome(destination_type="Redshift", outcome="skipped_incomplete")], 1
        )
        self.assertEqual(counts[CredentialBackfillOutcome(destination_type="Redshift", outcome="needs_integration")], 0)

    def test_undecryptable_connection_values_are_not_migrated(self) -> None:
        ciphertext = "gAAAAAfake-undecryptable-ciphertext"
        export = self._create(config={**INLINE, "password": ciphertext})
        original = deepcopy(export.destination.config)

        self.assertEqual(
            self._run(), {CredentialBackfillOutcome(destination_type="Redshift", outcome="skipped_unreadable"): 1}
        )

        export.destination.refresh_from_db()
        self.assertIsNone(export.destination.integration_id)
        self.assertEqual(export.destination.config, original)
        self.assertEqual(IntegrationManager.aws_redshift.credentials.list(self.team.id), [])
        self.assertEqual(IntegrationManager.aws_s3.credentials.list(self.team.id), [])
        self.sync.assert_not_called()

    def test_verify_fails_while_skipped_rows_remain(self) -> None:
        self._create(config={**INLINE, "password": ""})
        stdout = StringIO()

        with self.assertRaises(CommandError):
            call_command("backfill_batch_export_credentials", "--verify", stdout=stdout)

        self.assertIn("Redshift skipped_incomplete: 1", stdout.getvalue())

    def test_schedule_sync_uses_current_export_state(self) -> None:
        export = self._create()
        observed: list[bool] = []
        self.sync.side_effect = lambda batch_export, created: observed.append(batch_export.paused)

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            backfill_batch_export_credentials(execute=True)
        BatchExport.objects.filter(id=export.id).update(paused=True)
        for callback in callbacks:
            callback()

        self.assertEqual(observed, [True])

    def test_failed_destination_logs_identifier_and_exception_type(self) -> None:
        export = self._create()
        with (
            patch("products.batch_exports.backend.logic.credentials_backfill._plan", side_effect=RuntimeError(SECRET)),
            patch("products.batch_exports.backend.logic.credentials_backfill.logger") as logger,
        ):
            counts = self._run()

        self.assertEqual(counts, {CredentialBackfillOutcome(destination_type="Redshift", outcome="failed"): 1})
        logger.warning.assert_called_once_with(
            "batch_export_credentials.destination_failed",
            destination_id=str(export.destination.id),
            exception_type="RuntimeError",
        )
