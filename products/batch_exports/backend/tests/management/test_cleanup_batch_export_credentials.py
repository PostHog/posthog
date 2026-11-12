from __future__ import annotations

import hashlib
from collections import Counter
from copy import deepcopy
from io import StringIO
from typing import TYPE_CHECKING

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.integrations import IntegrationManager
from posthog.models.team import Team

from products.batch_exports.backend.logic.credentials_cleanup import (
    CredentialCleanupOutcome,
    cleanup_batch_export_credentials,
    verify_batch_export_credentials_cleanup,
)
from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination

if TYPE_CHECKING:
    from posthog.integrations import IntegrationRecord

SECRET = "obviously-fake-cleanup-secret-do-not-print"
AWS_PAIR = {"aws_access_key_id": "fake-access-key", "aws_secret_access_key": SECRET}
SHARED_COPY_ID = f"redshift-copy-{hashlib.sha256(b'fake-access-key').hexdigest()[:16]}"

# (destination type, integration kind, integration config, config to keep, config to remove)
CASES: dict[str, tuple[str, str, dict[str, object], dict[str, object], dict[str, object]]] = {
    "s3": (
        "AwsS3",
        "aws-s3",
        {"name": "fake"},
        {"bucket_name": "fake-bucket", "region": "us-east-1", "prefix": "fake/"},
        {**AWS_PAIR, "endpoint_url": "https://fake.example.com"},
    ),
    "s3_compatible": (
        "S3Compatible",
        "s3-compatible",
        {"name": "fake", "endpoint_url": "https://fake.example.com"},
        {"bucket_name": "fake-bucket", "region": "auto", "prefix": "fake/", "use_virtual_style_addressing": "True"},
        {**AWS_PAIR, "endpoint_url": "https://fake.example.com"},
    ),
    "snowflake": (
        "Snowflake",
        "snowflake",
        {"account": "fake-account", "user": "fake-user"},
        {"database": "fake-db", "warehouse": "fake-wh", "schema": "fake-schema", "role": "fake-role"},
        {
            "account": "fake-account",
            "user": "fake-user",
            "authentication_type": "keypair",
            "password": SECRET,
            "private_key": SECRET,
            "private_key_passphrase": SECRET,
        },
    ),
    "postgres": (
        "Postgres",
        "postgresql",
        {"host": "fake.example.com", "port": 5432, "user": "fake-user"},
        {"database": "fake-db", "schema": "public", "table_name": "events"},
        {
            "host": "fake.example.com",
            "port": "5432",
            "user": "fake-user",
            "password": SECRET,
            "has_self_signed_cert": "False",
        },
    ),
    "redshift": (
        "Redshift",
        "aws-redshift",
        {"host": "fake.example.com", "port": 5439, "user": "fake-user"},
        {"database": "fake-db", "schema": "public", "mode": "INSERT"},
        {"host": "fake.example.com", "port": "5439", "user": "fake-user", "password": SECRET},
    ),
    "redshift_aws_role": (
        "Redshift",
        "aws-redshift",
        {"aws_role_arn": "arn:aws:iam::123456789012:role/fake", "user": "fake-user"},
        {"database": "fake-db", "host": "fake.example.com", "port": "5439"},
        {"user": "fake-user", "password": SECRET},
    ),
    "bigquery": (
        "BigQuery",
        "google-cloud-service-account",
        {"project_id": "fake-project"},
        {"dataset_id": "fake-dataset", "table_id": "events", "project_id": "fake-project"},
        {
            "private_key": SECRET,
            "private_key_id": "fake-key-id",
            "token_uri": "https://oauth2.example.com/token",
            "client_email": "fake@example.com",
        },
    ),
}


def _outcomes(destination_type: str, **counts: int) -> Counter[CredentialCleanupOutcome]:
    return Counter(
        {
            CredentialCleanupOutcome(destination_type=destination_type, outcome=outcome): count
            for outcome, count in counts.items()
        }
    )


class TestCleanupBatchExportCredentials(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.sync = self.enterContext(
            patch("products.batch_exports.backend.logic.credentials_cleanup.sync_batch_export")
        )
        for boundary in (
            "socket.getaddrinfo",
            "requests.sessions.Session.request",
            "httpx.Client.send",
            "httpx.AsyncClient.send",
            "botocore.client.BaseClient._make_api_call",
        ):
            self.enterContext(patch(boundary, side_effect=AssertionError("Network access is disabled")))

    def _create_integration(
        self, kind: str, config: dict[str, object], *, team_id: int | None = None, external_id: str = "fake"
    ) -> IntegrationRecord:
        accessor = {
            "aws-s3": IntegrationManager.aws_s3.credentials,
            "s3-compatible": IntegrationManager.s3_compatible.credentials,
            "snowflake": IntegrationManager.snowflake.credentials,
            "postgresql": IntegrationManager.postgresql.credentials,
            "aws-redshift": IntegrationManager.aws_redshift.credentials,
            "google-cloud-service-account": IntegrationManager.google_cloud_service_account.credentials,
        }[kind]
        return accessor.create(
            self.team.id if team_id is None else team_id,
            external_id=external_id,
            config=config,
            sensitive_config={"password": SECRET},
        )

    def _create(
        self,
        destination_type: str,
        config: dict[str, object],
        *,
        integration_id: int | None,
        team_id: int | None = None,
    ) -> BatchExport:
        destination = BatchExportDestination.objects.create(
            type=destination_type, config=deepcopy(config), integration_id=integration_id
        )
        export = BatchExport.objects.create(
            team_id=self.team.id if team_id is None else team_id,
            name="Fake export",
            destination=destination,
            interval="hour",
        )
        destination.refresh_from_db()
        return export

    def _run(self, **kwargs: object) -> Counter[CredentialCleanupOutcome]:
        with self.captureOnCommitCallbacks(execute=True):
            return cleanup_batch_export_credentials(execute=True, **kwargs)  # type: ignore[arg-type]

    def _config(self, export: BatchExport) -> dict[str, object]:
        export.destination.refresh_from_db()
        return export.destination.config

    @parameterized.expand(CASES.keys())
    def test_preview_then_execute_removes_only_credential_fields(self, case: str) -> None:
        destination_type, kind, integration_config, keep, remove = CASES[case]
        integration = self._create_integration(kind, integration_config)
        export = self._create(destination_type, {**keep, **remove}, integration_id=integration.id)

        preview = cleanup_batch_export_credentials(execute=False)

        self.assertEqual(preview, _outcomes(destination_type, cleaned=1))
        self.assertEqual(self._config(export), {**keep, **remove})
        self.sync.assert_not_called()

        self.assertEqual(self._run(), _outcomes(destination_type, cleaned=1))

        self.assertEqual(self._config(export), keep)
        self.assertEqual(export.destination.integration_id, integration.id)
        self.sync.assert_called_once()
        self.assertEqual(self.sync.call_args.args[0].destination.config, keep)
        self.assertEqual(self._run(), _outcomes(destination_type, unchanged=1))
        self.sync.assert_called_once()

    @parameterized.expand([(False,), (True,)])
    def test_destination_without_integration_needs_the_flag(self, include: bool) -> None:
        _, _, _, keep, remove = CASES["postgres"]
        export = self._create("Postgres", {**keep, **remove}, integration_id=None)
        stdout = StringIO()

        with self.captureOnCommitCallbacks(execute=True):
            call_command(
                "cleanup_batch_export_credentials",
                "--execute",
                *(["--include-without-integration"] if include else []),
                stdout=stdout,
            )

        if include:
            self.assertIn("Postgres cleaned_without_integration: 1", stdout.getvalue())
            self.assertIn("Skipped without an integration: 0", stdout.getvalue())
            self.assertEqual(self._config(export), keep)
        else:
            self.assertIn("Postgres skipped_no_integration: 1", stdout.getvalue())
            self.assertIn("Skipped without an integration: 1", stdout.getvalue())
            self.assertEqual(self._config(export), {**keep, **remove})
            self.sync.assert_not_called()
        self.assertIsNone(export.destination.integration_id)

        stdout = StringIO()
        call_command("cleanup_batch_export_credentials", "--verify", stdout=stdout)
        self.assertIn(f"Skipped without an integration: {int(not include)}", stdout.getvalue())
        if not include:
            with self.assertRaises(CommandError):
                call_command(
                    "cleanup_batch_export_credentials", "--verify", "--include-without-integration", stdout=StringIO()
                )

    @parameterized.expand(
        [
            ("other_team", "postgresql", "skipped_integration_missing"),
            ("wrong_kind", "snowflake", "skipped_integration_wrong_kind"),
        ]
    )
    def test_unusable_integration_is_skipped(self, variant: str, kind: str, outcome: str) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Fake other team")
        integration = self._create_integration(
            kind, {"host": "fake.example.com"}, team_id=other_team.id if variant == "other_team" else None
        )
        _, _, _, keep, remove = CASES["postgres"]
        export = self._create("Postgres", {**keep, **remove}, integration_id=integration.id)

        self.assertEqual(self._run(include_without_integration=True), _outcomes("Postgres", **{outcome: 1}))

        self.assertEqual(self._config(export), {**keep, **remove})
        self.sync.assert_not_called()
        stdout = StringIO()
        with self.assertRaises(CommandError):
            call_command("cleanup_batch_export_credentials", "--verify", stdout=stdout)
        self.assertIn(f"Postgres {outcome}: 1", stdout.getvalue())

    @parameterized.expand(
        [
            ("create", None, "copy_integration_created"),
            ("reuse", ("Fake user keys", SECRET), "copy_integration_reused"),
            ("conflict", (SHARED_COPY_ID, "fake-other-secret"), "copy_integration_created"),
            ("unreadable", None, None),
            ("double_conflict", (SHARED_COPY_ID, "fake-other-secret"), None),
        ]
    )
    def test_redshift_copy_keys_move_to_an_s3_integration(
        self, variant: str, existing: tuple[str, str] | None, copy_outcome: str | None
    ) -> None:
        redshift = self._create_integration("aws-redshift", {"host": "fake.example.com", "port": 5439, "user": "u"})
        pair = (
            {**AWS_PAIR, "aws_secret_access_key": "gAAAAAfake-undecryptable-ciphertext"}
            if variant == "unreadable"
            else AWS_PAIR
        )
        copy_inputs: dict[str, object] = {
            "s3_bucket": "fake-bucket",
            "region_name": "us-east-1",
            "s3_key_prefix": "fake/",
            "bucket_credentials": pair,
            "authorization": pair,
        }
        config: dict[str, object] = {
            "database": "fake-db",
            "mode": "COPY",
            "password": SECRET,
            "copy_inputs": copy_inputs,
        }
        export = self._create("Redshift", config, integration_id=redshift.id)
        s3 = IntegrationManager.aws_s3.credentials
        existing_row = None
        if existing is not None:
            existing_row = s3.create(
                self.team.id,
                external_id=existing[0],
                config={"name": existing[0]},
                sensitive_config={**AWS_PAIR, "aws_secret_access_key": existing[1]},
            )
        if variant == "double_conflict":
            s3.create(
                self.team.id,
                external_id=f"{SHARED_COPY_ID}-{export.destination.id}",
                config={},
                sensitive_config={**AWS_PAIR, "aws_secret_access_key": "fake-third-secret"},
            )
        before = {row.id for row in s3.list(self.team.id)}

        counts = self._run()

        if copy_outcome is None:
            expected = "skipped_unreadable" if variant == "unreadable" else "skipped_conflict"
            self.assertEqual(counts, _outcomes("Redshift", **{expected: 1}))
            self.assertEqual(self._config(export), config)
            self.assertEqual({row.id for row in s3.list(self.team.id)}, before)
            return

        self.assertEqual(counts, _outcomes("Redshift", cleaned=1, **{copy_outcome: 1}))
        stored = self._config(export)
        self.assertNotIn("password", stored)
        stored_copy = stored["copy_inputs"]
        assert isinstance(stored_copy, dict)
        self.assertEqual(stored_copy["bucket_credentials"], stored_copy["authorization"])
        row = s3.get(self.team.id, int(stored_copy["bucket_credentials"]))
        self.assertEqual(dict(row.sensitive_config), AWS_PAIR)
        self.assertEqual(
            {k: v for k, v in stored_copy.items() if k not in ("bucket_credentials", "authorization")},
            {"s3_bucket": "fake-bucket", "region_name": "us-east-1", "s3_key_prefix": "fake/"},
        )
        if variant == "reuse":
            assert existing_row is not None
            self.assertEqual(row.id, existing_row.id)
            self.assertEqual({r.id for r in s3.list(self.team.id)}, before)
        else:
            expected_external_id = (
                SHARED_COPY_ID if variant == "create" else f"{SHARED_COPY_ID}-{export.destination.id}"
            )
            self.assertEqual(row.integration_id, expected_external_id)
        if existing_row is not None and variant == "conflict":
            unchanged = s3.get(self.team.id, existing_row.id)
            self.assertEqual(unchanged.sensitive_config["aws_secret_access_key"], "fake-other-secret")
        self.assertEqual(self._run(), _outcomes("Redshift", unchanged=1))

    def test_bigquery_integration_with_an_unusable_key_keeps_the_inline_fallback(self) -> None:
        integration = IntegrationManager.google_cloud_service_account.credentials.create(
            self.team.id,
            external_id="fake-bigquery",
            config={"project_id": "fake-project", "service_account_email": "fake@example.com"},
            sensitive_config={
                "private_key": "not-a-private-key",
                "private_key_id": "fake-key-id",
                "token_uri": "https://oauth2.googleapis.com/token",
            },
        )
        _, _, _, keep, remove = CASES["bigquery"]
        export = self._create("BigQuery", {**keep, **remove}, integration_id=integration.id)

        self.assertEqual(self._run(), _outcomes("BigQuery", skipped_integration_invalid=1))
        self.assertEqual(self._config(export), {**keep, **remove})
        self.sync.assert_not_called()

    def test_redshift_copy_keys_reuse_distinct_integrations_without_external_ids(self) -> None:
        redshift = self._create_integration("aws-redshift", {"host": "fake.example.com", "port": 5439, "user": "u"})
        s3 = IntegrationManager.aws_s3.credentials
        other_pair = {"aws_access_key_id": "fake-other-access-key", "aws_secret_access_key": "fake-other-secret"}
        first = s3.create(self.team.id, external_id=None, config={"name": "first"}, sensitive_config=AWS_PAIR)
        second = s3.create(self.team.id, external_id=None, config={"name": "second"}, sensitive_config=other_pair)
        copy_inputs: dict[str, object] = {
            "s3_bucket": "fake-bucket",
            "bucket_credentials": AWS_PAIR,
            "authorization": other_pair,
        }
        export = self._create(
            "Redshift", {"database": "fake-db", "mode": "COPY", "copy_inputs": copy_inputs}, integration_id=redshift.id
        )

        counts = self._run()

        self.assertEqual(counts, _outcomes("Redshift", cleaned=1, copy_integration_reused=2))
        stored_copy = self._config(export)["copy_inputs"]
        assert isinstance(stored_copy, dict)
        self.assertEqual(int(stored_copy["bucket_credentials"]), first.id)
        self.assertEqual(int(stored_copy["authorization"]), second.id)

    @parameterized.expand([("ciphertext", "gAAAAAfake-undecryptable-ciphertext"), ("invalid_json", "{not json")])
    def test_redshift_unreadable_copy_inputs_are_unresolved(self, _name: str, raw_copy_inputs: str) -> None:
        redshift = self._create_integration("aws-redshift", {"host": "fake.example.com", "port": 5439, "user": "u"})
        config: dict[str, object] = {"database": "fake-db", "mode": "COPY", "copy_inputs": raw_copy_inputs}
        export = self._create("Redshift", config, integration_id=redshift.id)

        self.assertEqual(self._run(), _outcomes("Redshift", skipped_unreadable=1))
        self.assertEqual(self._config(export), config)
        self.assertEqual(verify_batch_export_credentials_cleanup(), _outcomes("Redshift", skipped_unreadable=1))

    def test_schedule_sync_failure_is_counted_and_run_continues(self) -> None:
        destination_type, kind, integration_config, keep, remove = CASES["postgres"]
        integration = self._create_integration(kind, integration_config)
        exports = [self._create(destination_type, {**keep, **remove}, integration_id=integration.id) for _ in range(2)]
        self.sync.side_effect = RuntimeError(SECRET)

        with patch("products.batch_exports.backend.logic.credentials_cleanup.logger") as logger:
            counts = self._run()

        self.assertEqual(counts, _outcomes("Postgres", cleaned=2, schedule_sync_failed=2))
        for export in exports:
            self.assertEqual(self._config(export), keep)
        self.assertEqual(logger.warning.call_count, 2)
        for call in logger.warning.call_args_list:
            self.assertEqual(call.kwargs["exception_type"], "RuntimeError")
            self.assertNotIn(SECRET, str(call))

    def test_verify_before_and_after_and_never_prints_credentials(self) -> None:
        destination_type, kind, integration_config, keep, remove = CASES["snowflake"]
        integration = self._create_integration(kind, integration_config)
        self._create(destination_type, {**keep, **remove}, integration_id=integration.id)
        output = StringIO()

        with self.assertRaises(CommandError) as raised:
            call_command("cleanup_batch_export_credentials", "--verify", stdout=output, stderr=output)
        self.assertIn("Snowflake needs_cleanup: 1", output.getvalue())

        with self.captureOnCommitCallbacks(execute=True):
            call_command("cleanup_batch_export_credentials", stdout=output, stderr=output)
            call_command("cleanup_batch_export_credentials", "--execute", stdout=output, stderr=output)
        verify_output = StringIO()
        call_command("cleanup_batch_export_credentials", "--verify", stdout=verify_output)

        self.assertIn("Total outcomes: 0", verify_output.getvalue())
        self.assertNotIn(SECRET, output.getvalue() + verify_output.getvalue() + str(raised.exception))

    @parameterized.expand([("team",), ("type",)])
    def test_command_filters(self, variant: str) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Fake other team")
        _, pg_kind, pg_integration, pg_keep, pg_remove = CASES["postgres"]
        _, bq_kind, bq_integration, bq_keep, bq_remove = CASES["bigquery"]
        selected = self._create(
            "Postgres", {**pg_keep, **pg_remove}, integration_id=self._create_integration(pg_kind, pg_integration).id
        )
        other = (
            self._create(
                "Postgres",
                {**pg_keep, **pg_remove},
                integration_id=self._create_integration(pg_kind, pg_integration, team_id=other_team.id).id,
                team_id=other_team.id,
            )
            if variant == "team"
            else self._create(
                "BigQuery",
                {**bq_keep, **bq_remove},
                integration_id=self._create_integration(bq_kind, bq_integration).id,
            )
        )
        args = ["--team-id", str(self.team.id)] if variant == "team" else ["--type", "Postgres"]

        with self.captureOnCommitCallbacks(execute=True):
            call_command("cleanup_batch_export_credentials", "--execute", *args, stdout=StringIO())

        self.assertEqual(self._config(selected), pg_keep)
        self.assertNotEqual(self._config(other), self._config(selected))
