from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from copy import deepcopy
from io import StringIO
from typing import TYPE_CHECKING, cast

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction

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
INLINE: dict[str, dict[str, object]] = {
    "Postgres": {
        "host": "fake.example.com",
        "user": "fake-user",
        "password": SECRET,
        "port": "5432",
        "database": "fake-database",
        "has_self_signed_cert": "true",
    },
    "Redshift": {
        "host": "fake.example.com",
        "user": "fake-user",
        "password": SECRET,
        "port": "5439",
        "database": "fake-database",
        **AWS_PAIR,
    },
    "BigQuery": {
        "project_id": "fake-project",
        "client_email": "fake@example.com",
        "private_key": SECRET,
        "private_key_id": "fake-key-id",
        "token_uri": "https://oauth2.googleapis.com/token",
        "dataset_id": "fake-dataset",
    },
    "AwsS3": {**AWS_PAIR, "bucket_name": "fake-bucket", "region": "fake-region"},
    "Snowflake": {
        "account": "fake-account",
        "user": "fake-user",
        "password": SECRET,
        "authentication_type": "password",
        "database": "fake-database",
        "schema": "fake-schema",
        "warehouse": "fake-warehouse",
    },
}
ACCESSORS = {
    "Postgres": IntegrationManager.postgresql.credentials,
    "Redshift": IntegrationManager.aws_redshift.credentials,
    "BigQuery": IntegrationManager.google_cloud_service_account.credentials,
    "AwsS3": IntegrationManager.aws_s3.credentials,
    "Snowflake": IntegrationManager.snowflake.credentials,
}
KINDS = {
    "Postgres": "postgresql",
    "Redshift": "aws-redshift",
    "BigQuery": "google-cloud-service-account",
    "AwsS3": "aws-s3",
    "Snowflake": "snowflake",
}
REMOVED = {
    "Postgres": {"user", "password"},
    "Redshift": {"user", "password", "aws_access_key_id", "aws_secret_access_key"},
    "BigQuery": {"private_key", "private_key_id", "token_uri", "client_email"},
    "AwsS3": {"aws_access_key_id", "aws_secret_access_key"},
    "Snowflake": {"user", "password", "private_key", "private_key_passphrase"},
}


def _expected_config(destination_type: str, name: str) -> dict[str, object]:
    if destination_type in ("Postgres", "Redshift"):
        return {
            "host": "fake.example.com",
            "port": 5432 if destination_type == "Postgres" else 5439,
            "user": "fake-user",
            "ssl_mode": "require",
            "ssl_root_cert": None,
        }
    if destination_type == "BigQuery":
        return {"project_id": "fake-project", "service_account_email": "fake@example.com"}
    if destination_type == "Snowflake":
        return {"name": name, "account": "fake-account", "user": "fake-user", "authentication_type": "password"}
    return {"name": name}


def _expected_secrets(destination_type: str) -> dict[str, object]:
    if destination_type == "AwsS3":
        return dict(AWS_PAIR)
    if destination_type == "BigQuery":
        return {
            "private_key": SECRET,
            "private_key_id": "fake-key-id",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    return {"password": SECRET}


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
        destination_type: str = "Postgres",
        *,
        config: object | None = None,
        name: str = "Fake export",
        integration_id: int | None = None,
        team_id: int | None = None,
        deleted: bool = False,
        paused: bool = False,
    ) -> BatchExport:
        destination = BatchExportDestination.objects.create(
            type=destination_type,
            config=deepcopy(INLINE[destination_type] if config is None else config),
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

    def _existing(self, export: BatchExport, *, conflict: bool = False) -> IntegrationRecord:
        destination_type = export.destination.type
        name = f"{export.name} ({str(export.destination.id)[:8]})"
        config = _expected_config(destination_type, name)
        external_id = name
        if destination_type in ("Postgres", "Redshift"):
            external_id = f"{export.team_id}-fake.example.com-{config['port']}-fake-user"
        elif destination_type == "BigQuery":
            external_id = f"fake@example.com-{export.team_id}-key-file"
        return ACCESSORS[destination_type].create(
            export.team_id,
            external_id=external_id,
            config=config,
            sensitive_config=(
                {"fake-conflict": "fake-other-secret"} if conflict else _expected_secrets(destination_type)
            ),
        )

    @parameterized.expand([(kind,) for kind in INLINE])
    def test_moves_credentials_and_second_run_changes_nothing(self, destination_type: str) -> None:
        export = self._create(destination_type)
        original = deepcopy(export.destination.config)

        self.assertEqual(
            self._run(),
            {CredentialBackfillOutcome(destination_type=destination_type, outcome="integration_created"): 1},
        )

        export.destination.refresh_from_db()
        row = ACCESSORS[destination_type].get(self.team.id, cast(int, export.destination.integration_id))
        name = f"{export.name} ({str(export.destination.id)[:8]})"
        self.assertEqual(row.kind, KINDS[destination_type])
        self.assertEqual(row.config, _expected_config(destination_type, name))
        self.assertEqual(row.sensitive_config, _expected_secrets(destination_type))
        self.assertEqual(
            export.destination.config,
            {key: value for key, value in original.items() if key not in REMOVED[destination_type]},
        )
        self.sync.assert_called_once_with(export, created=False)
        self.assertEqual(self.sync.call_args.args[0].destination.integration_id, row.id)
        self.assertEqual(self.sync.call_args.args[0].destination.config, export.destination.config)
        self.assertEqual(
            self._run(), {CredentialBackfillOutcome(destination_type=destination_type, outcome="unchanged"): 1}
        )
        self.assertEqual(len(ACCESSORS[destination_type].list(self.team.id)), 1)
        self.sync.assert_called_once()

    @parameterized.expand([(kind,) for kind in INLINE])
    def test_preview_writes_nothing(self, destination_type: str) -> None:
        export = self._create(destination_type)
        original = deepcopy(export.destination.config)

        self.assertEqual(
            self._run(execute=False),
            {CredentialBackfillOutcome(destination_type=destination_type, outcome="integration_created"): 1},
        )

        export.destination.refresh_from_db()
        self.assertIsNone(export.destination.integration_id)
        self.assertEqual(export.destination.config, original)
        self.assertEqual(ACCESSORS[destination_type].list(self.team.id), [])
        self.sync.assert_not_called()

    @parameterized.expand([(kind,) for kind in INLINE])
    def test_matching_integration_is_reused(self, destination_type: str) -> None:
        export = self._create(destination_type)
        row = self._existing(export)

        self.assertEqual(
            self._run(),
            {CredentialBackfillOutcome(destination_type=destination_type, outcome="integration_reused"): 1},
        )

        export.destination.refresh_from_db()
        self.assertEqual(export.destination.integration_id, row.id)
        self.assertEqual(len(ACCESSORS[destination_type].list(self.team.id)), 1)

    @parameterized.expand([(kind,) for kind in INLINE])
    def test_conflicting_integration_leaves_destination_unchanged(self, destination_type: str) -> None:
        export = self._create(destination_type)
        row = self._existing(export, conflict=True)
        original = deepcopy(export.destination.config)

        self.assertEqual(
            self._run(), {CredentialBackfillOutcome(destination_type=destination_type, outcome="skipped_conflict"): 1}
        )

        export.destination.refresh_from_db()
        self.assertIsNone(export.destination.integration_id)
        self.assertEqual(export.destination.config, original)
        self.assertEqual(ACCESSORS[destination_type].get(self.team.id, row.id).sensitive_config, row.sensitive_config)
        self.sync.assert_not_called()

    @parameterized.expand([(kind,) for kind in INLINE])
    def test_existing_link_strips_only_stale_secrets(self, destination_type: str) -> None:
        export = self._create(destination_type)
        row = self._existing(export)
        export.destination.integration_id = row.id
        export.destination.save(update_fields=["integration_id"])
        original = deepcopy(export.destination.config)
        is_bigquery = destination_type == "BigQuery"

        counts = self._run()

        export.destination.refresh_from_db()
        self.assertEqual(
            counts,
            {
                CredentialBackfillOutcome(
                    destination_type=destination_type,
                    outcome="unchanged" if is_bigquery else "stale_secrets_removed",
                ): 1
            },
        )
        expected = (
            original
            if is_bigquery
            else {key: value for key, value in original.items() if key not in REMOVED[destination_type]}
        )
        self.assertEqual(export.destination.config, expected)
        self.assertEqual(self.sync.call_count, 0 if is_bigquery else 1)
        self.assertEqual(verify_batch_export_credentials(), {})

    @parameterized.expand(
        [
            ("Postgres", {"password": ""}),
            ("Postgres", {"host": " "}),
            ("Postgres", {"user": None}),
            ("Postgres", {"port": "not-an-integer"}),
            ("Postgres", {"port": "1.5"}),
            ("Redshift", {"password": None}),
            ("Redshift", {"port": ""}),
            ("BigQuery", {"private_key_id": ""}),
            ("BigQuery", {"project_id": None}),
            ("BigQuery", {"token_uri": "https://example.com/token"}),
            ("AwsS3", {"aws_secret_access_key": " "}),
            ("AwsS3", {"aws_access_key_id": None}),
            ("Snowflake", {"password": ""}),
            ("Snowflake", {"account": "https://example.com"}),
            ("Snowflake", {"authentication_type": "fake-unsupported"}),
            ("Snowflake", {"authentication_type": "keypair", "private_key": ""}),
        ]
    )
    def test_incomplete_credentials_are_not_written(self, destination_type: str, overrides: dict[str, object]) -> None:
        export = self._create(destination_type, config={**INLINE[destination_type], **overrides})
        original = deepcopy(export.destination.config)

        self.assertEqual(
            self._run(),
            {CredentialBackfillOutcome(destination_type=destination_type, outcome="skipped_incomplete"): 1},
        )

        export.destination.refresh_from_db()
        self.assertIsNone(export.destination.integration_id)
        self.assertEqual(export.destination.config, original)
        self.assertEqual(ACCESSORS[destination_type].list(self.team.id), [])
        self.sync.assert_not_called()

    @parameterized.expand([("fake-unreadable",), (["fake-unreadable"],)])
    def test_unreadable_config_is_not_written(self, config: object) -> None:
        export = self._create(config=config)

        self.assertEqual(
            self._run(), {CredentialBackfillOutcome(destination_type="Postgres", outcome="skipped_unreadable"): 1}
        )
        self.assertEqual(
            verify_batch_export_credentials(),
            {CredentialBackfillOutcome(destination_type="Postgres", outcome="skipped_unreadable"): 1},
        )

        export.destination.refresh_from_db()
        self.assertEqual(export.destination.config, config)
        self.assertIsNone(export.destination.integration_id)
        self.assertEqual(IntegrationManager.postgresql.credentials.list(self.team.id), [])
        self.sync.assert_not_called()

    @parameterized.expand([("Postgres", 5432), ("Redshift", 5439)])
    def test_missing_port_uses_destination_default(self, destination_type: str, expected_port: int) -> None:
        config = {key: value for key, value in INLINE[destination_type].items() if key != "port"}
        export = self._create(destination_type, config=config)

        self._run()

        export.destination.refresh_from_db()
        row = ACCESSORS[destination_type].get(self.team.id, cast(int, export.destination.integration_id))
        self.assertEqual(row.config["port"], expected_port)
        self.assertNotIn("port", export.destination.config)

    @parameterized.expand([(False, ""), (False, "fake-passphrase"), (True, "fake-passphrase"), (True, " ")])
    def test_snowflake_keypair_and_authentication_default(self, explicit_type: bool, passphrase: str) -> None:
        config = {
            key: value for key, value in INLINE["Snowflake"].items() if key not in ("password", "authentication_type")
        }
        config.update(private_key=SECRET, private_key_passphrase=passphrase)
        if explicit_type:
            config["authentication_type"] = "keypair"
        export = self._create("Snowflake", config=config)

        self._run()

        export.destination.refresh_from_db()
        row = IntegrationManager.snowflake.credentials.get(self.team.id, cast(int, export.destination.integration_id))
        self.assertEqual(row.config["authentication_type"], "keypair")
        self.assertEqual(
            row.sensitive_config,
            {"private_key": SECRET, **({"private_key_passphrase": passphrase} if passphrase else {})},
        )
        self.assertTrue(REMOVED["Snowflake"].isdisjoint(export.destination.config))

    @parameterized.expand([(False,), (True,)])
    def test_copy_pairs_share_or_split_integrations(self, distinct: bool) -> None:
        second = {**AWS_PAIR, "aws_secret_access_key": "fake-second-secret"} if distinct else AWS_PAIR
        export = self._create(
            "Redshift",
            config={
                **INLINE["Redshift"],
                "copy_inputs": {
                    "bucket_credentials": AWS_PAIR,
                    "authorization": second,
                    "s3_bucket": "fake-bucket",
                    "region_name": "fake-region",
                },
            },
        )

        counts = self._run()

        export.destination.refresh_from_db()
        copy = export.destination.config["copy_inputs"]
        bucket = IntegrationManager.aws_s3.credentials.get(self.team.id, int(copy["bucket_credentials"]))
        authorization = IntegrationManager.aws_s3.credentials.get(self.team.id, int(copy["authorization"]))
        self.assertEqual(bucket.sensitive_config, AWS_PAIR)
        self.assertEqual(authorization.sensitive_config, second)
        self.assertEqual(bucket.id == authorization.id, not distinct)
        name = f"Fake export COPY credentials ({str(export.destination.id)[:8]})"
        self.assertEqual(bucket.config, {"name": name})
        self.assertEqual(authorization.config, {"name": f"{name} 2" if distinct else name})
        self.assertEqual(copy["s3_bucket"], "fake-bucket")
        self.assertEqual(copy["region_name"], "fake-region")
        self.assertEqual(
            counts[CredentialBackfillOutcome(destination_type="Redshift", outcome="copy_credentials_moved")], 1
        )
        self.assertIsInstance(self.sync.call_args.args[0].destination.config["copy_inputs"]["authorization"], int)
        self.assertEqual(len(IntegrationManager.aws_s3.credentials.list(self.team.id)), 2 if distinct else 1)
        self.assertEqual(self._run(), {CredentialBackfillOutcome(destination_type="Redshift", outcome="unchanged"): 1})
        self.sync.assert_called_once()

    @parameterized.expand([("role",), ("id",), ("digit_string",), ("incomplete",)])
    def test_copy_leaves_other_values_untouched(self, variant: str) -> None:
        value: object = "arn:aws:iam::000000000000:role/fake-role"
        if variant in ("id", "digit_string"):
            row = IntegrationManager.aws_s3.credentials.create(
                self.team.id,
                external_id="fake-existing",
                config={"name": "fake-existing"},
                sensitive_config=AWS_PAIR,
            )
            value = row.id if variant == "id" else str(row.id)
        elif variant == "incomplete":
            value = {"aws_access_key_id": "fake-access-key"}
        export = self._create(
            "Redshift",
            config={
                **INLINE["Redshift"],
                "copy_inputs": {"bucket_credentials": AWS_PAIR, "authorization": value},
            },
        )
        original = deepcopy(export.destination.config["copy_inputs"]["authorization"])

        counts = self._run()

        export.destination.refresh_from_db()
        self.assertEqual(export.destination.config["copy_inputs"]["authorization"], original)
        self.assertEqual(
            counts[CredentialBackfillOutcome(destination_type="Redshift", outcome="copy_credentials_moved")], 1
        )
        self.assertEqual(
            counts[CredentialBackfillOutcome(destination_type="Redshift", outcome="copy_skipped_incomplete")],
            int(variant == "incomplete"),
        )

    @parameterized.expand([("incomplete",), ("linked",), ("preview",)])
    def test_copy_is_independent_of_connection_creation(self, variant: str) -> None:
        export = self._create("Redshift", config={**INLINE["Redshift"], "copy_inputs": {"authorization": AWS_PAIR}})
        if variant == "incomplete":
            export.destination.config.pop("password")
        elif variant == "linked":
            export.destination.integration_id = self._existing(export).id
        export.destination.save(update_fields=["config", "integration_id"])
        original = deepcopy(export.destination.config)

        counts = self._run(execute=variant != "preview")

        export.destination.refresh_from_db()
        self.assertEqual(
            counts[CredentialBackfillOutcome(destination_type="Redshift", outcome="copy_credentials_moved")], 1
        )
        if variant == "preview":
            self.assertEqual(export.destination.config, original)
            self.assertEqual(IntegrationManager.aws_s3.credentials.list(self.team.id), [])
            self.sync.assert_not_called()
        else:
            copy_id = int(export.destination.config["copy_inputs"]["authorization"])
            self.assertEqual(
                IntegrationManager.aws_s3.credentials.get(self.team.id, copy_id).sensitive_config, AWS_PAIR
            )
            if variant == "incomplete":
                self.assertIsNone(export.destination.integration_id)
                self.assertIn("user", export.destination.config)
                self.assertEqual(
                    counts[CredentialBackfillOutcome(destination_type="Redshift", outcome="skipped_incomplete")], 1
                )

    def test_copy_conflict_prevents_all_destination_writes(self) -> None:
        export = self._create("Redshift", config={**INLINE["Redshift"], "copy_inputs": {"authorization": AWS_PAIR}})
        name = f"Fake export COPY credentials ({str(export.destination.id)[:8]})"
        IntegrationManager.aws_s3.credentials.create(
            self.team.id,
            external_id=name,
            config={"name": name},
            sensitive_config={**AWS_PAIR, "aws_secret_access_key": "fake-conflict"},
        )
        original = deepcopy(export.destination.config)

        self.assertEqual(
            self._run(), {CredentialBackfillOutcome(destination_type="Redshift", outcome="skipped_conflict"): 1}
        )

        export.destination.refresh_from_db()
        self.assertIsNone(export.destination.integration_id)
        self.assertEqual(export.destination.config, original)
        self.assertEqual(IntegrationManager.aws_redshift.credentials.list(self.team.id), [])
        self.sync.assert_not_called()

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
        exports = [self._create(), self._create("AwsS3"), self._create("Snowflake", team_id=other_team.id)]
        args = {
            "team": ["--team-id", str(self.team.id)],
            "type": ["--type", "AwsS3"],
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
            "team": exports[:2],
            "type": [exports[1]],
            "limit": [min(exports, key=lambda export: export.destination.id)],
            "zero": [],
        }[variant]
        self.assertEqual({export.id for export in changed}, {export.id for export in expected})
        self.sync.assert_not_called()

    def test_batch_callback_and_limit(self) -> None:
        for index in range(3):
            self._create("AwsS3", name=f"Fake export {index}")
        on_batch = Mock()

        self._run(batch_size=1, limit=2, on_batch=on_batch)

        self.assertEqual([call.args[0] for call in on_batch.call_args_list], [1, 1])
        self.assertEqual(len(IntegrationManager.aws_s3.credentials.list(self.team.id)), 2)

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
            counts[CredentialBackfillOutcome(destination_type="Postgres", outcome="schedule_sync_failed")], int(fails)
        )
        if fails:
            logger.warning.assert_called_once_with(
                "batch_export_credentials.schedule_sync_failed",
                export_id=str(export.id),
                exception_type="RuntimeError",
            )
        else:
            logger.warning.assert_not_called()

    @parameterized.expand(
        [("connection", "needs_integration"), ("copy", "needs_copy_move"), ("stale", "needs_stale_strip")]
    )
    def test_verify_before_and_after_backfill(self, variant: str, outcome: str) -> None:
        export = self._create("Redshift" if variant == "copy" else "Postgres")
        if variant in ("copy", "stale"):
            export.destination.integration_id = self._existing(export).id
        if variant == "copy":
            export.destination.config["copy_inputs"] = {"authorization": AWS_PAIR}
        export.destination.save(update_fields=["config", "integration_id"])
        stdout = StringIO()

        with self.assertRaises(CommandError):
            call_command("backfill_batch_export_credentials", "--verify", stdout=stdout)

        self.assertIn(f"{outcome}: 1", stdout.getvalue())
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
        self.assertEqual(IntegrationManager.postgresql.credentials.list(self.team.id), [])
        self.sync.assert_not_called()

    def test_copy_reuses_matching_integration(self) -> None:
        export = self._create("Redshift", config={**INLINE["Redshift"], "copy_inputs": {"authorization": AWS_PAIR}})
        name = f"Fake export COPY credentials ({str(export.destination.id)[:8]})"
        row = IntegrationManager.aws_s3.credentials.create(
            self.team.id, external_id=name, config={"name": name}, sensitive_config=AWS_PAIR
        )

        self._run()

        export.destination.refresh_from_db()
        self.assertEqual(int(export.destination.config["copy_inputs"]["authorization"]), row.id)
        self.assertEqual(len(IntegrationManager.aws_s3.credentials.list(self.team.id)), 1)

    @parameterized.expand([("connection",), ("copy",)])
    def test_verify_incomplete_rows_remain_visible(self, variant: str) -> None:
        config: dict[str, object] = {}
        if variant == "copy":
            config["copy_inputs"] = {"authorization": {"aws_access_key_id": "fake-key"}}
        self._create("Redshift", config=config)

        counts = verify_batch_export_credentials()

        self.assertEqual(
            counts[CredentialBackfillOutcome(destination_type="Redshift", outcome="skipped_incomplete")], 1
        )
        self.assertEqual(counts[CredentialBackfillOutcome(destination_type="Redshift", outcome="needs_integration")], 0)
        self.assertEqual(counts[CredentialBackfillOutcome(destination_type="Redshift", outcome="needs_copy_move")], 0)
        if variant == "copy":
            self.assertEqual(
                counts[CredentialBackfillOutcome(destination_type="Redshift", outcome="copy_skipped_incomplete")], 1
            )
