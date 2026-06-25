from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.local_bootstrap import (
    BootstrapConfig,
    BootstrapConfigError,
    DiscoveredFile,
    Progress,
    S3Location,
    TableImportConfig,
    TablePlan,
    list_files,
    run_bootstrap,
)
from posthog.local_bootstrap.config import SUPPORTED_FILE_FORMATS


def _format_bytes(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


class Command(BaseCommand):
    help = (
        "Bootstrap a local PostHog project from an S3 dump of the events and/or persons tables. "
        "The dump must be in the PostHog batch-export format (Parquet or JSONLines, optionally "
        "compressed). Events go to ClickHouse; persons go to Postgres and ClickHouse."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--name", help="Project name (prompted if omitted)")
        parser.add_argument("--email", help="Email for the project owner account (prompted if omitted)")
        parser.add_argument("--password", default="12345678", help="Password for the owner account (default 12345678)")

        parser.add_argument("--events-bucket", help="S3 bucket holding the events dump")
        parser.add_argument("--events-prefix", default="", help="Key prefix for the events dump")
        parser.add_argument("--persons-bucket", help="S3 bucket holding the persons dump")
        parser.add_argument("--persons-prefix", default="", help="Key prefix for the persons dump")

        parser.add_argument("--aws-access-key-id", help="AWS access key id (falls back to ambient AWS config)")
        parser.add_argument("--aws-secret-access-key", help="AWS secret access key")
        parser.add_argument("--aws-region", help="AWS region")
        parser.add_argument("--aws-endpoint-url", help="Custom S3 endpoint (MinIO, SeaweedFS, R2, ...)")

        # Persons may live in a different account/bucket; these override the shared creds for persons.
        parser.add_argument("--persons-aws-access-key-id")
        parser.add_argument("--persons-aws-secret-access-key")
        parser.add_argument("--persons-aws-region")
        parser.add_argument("--persons-aws-endpoint-url")

        parser.add_argument(
            "--format", default="Parquet", choices=SUPPORTED_FILE_FORMATS, help="Dump file format (default Parquet)"
        )
        parser.add_argument("--compression", default="zstd", help="Compression codec, or 'none' (default zstd)")
        parser.add_argument("--batch-size", type=int, default=10_000, help="Rows per insert batch (default 10000)")
        parser.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG and not settings.TEST:
            raise CommandError("bootstrap_local_project is a local-development tool and refuses to run in production")

        name = options["name"] or self._prompt("Project name")
        email = options["email"] or self._prompt("Owner email")
        compression = None if options["compression"] in ("none", "") else options["compression"]

        config = self._build_config(name, email, compression, options)
        try:
            config.validate()
        except BootstrapConfigError as error:
            raise CommandError(str(error))

        plans = self._discover(config)
        self._print_plan_report(config, plans)

        if not options["yes"] and not self._confirm("\nProceed with the import?"):
            self.stdout.write(self.style.WARNING("Aborted."))
            return

        report = run_bootstrap(config, plans, self._progress())
        self.stdout.write("")  # close the progress line
        self._print_final_report(report)

    def _build_config(self, name: str, email: str, compression: str | None, options: dict[str, Any]) -> BootstrapConfig:
        shared = {
            "access_key_id": options["aws_access_key_id"],
            "secret_access_key": options["aws_secret_access_key"],
            "region": options["aws_region"],
            "endpoint_url": options["aws_endpoint_url"],
        }
        tables: list[TableImportConfig] = []

        if options["events_bucket"]:
            tables.append(
                TableImportConfig(
                    table="events",
                    location=S3Location(bucket=options["events_bucket"], prefix=options["events_prefix"], **shared),
                    file_format=options["format"],
                    compression=compression,
                )
            )

        if options["persons_bucket"]:
            tables.append(
                TableImportConfig(
                    table="persons",
                    location=S3Location(
                        bucket=options["persons_bucket"],
                        prefix=options["persons_prefix"],
                        access_key_id=options["persons_aws_access_key_id"] or shared["access_key_id"],
                        secret_access_key=options["persons_aws_secret_access_key"] or shared["secret_access_key"],
                        region=options["persons_aws_region"] or shared["region"],
                        endpoint_url=options["persons_aws_endpoint_url"] or shared["endpoint_url"],
                    ),
                    file_format=options["format"],
                    compression=compression,
                )
            )

        if not tables:
            raise CommandError("Provide at least one of --events-bucket or --persons-bucket")

        return BootstrapConfig(
            project_name=name,
            email=email,
            password=options["password"],
            tables=tables,
            batch_size=options["batch_size"],
        )

    def _discover(self, config: BootstrapConfig) -> list[TablePlan]:
        plans: list[TablePlan] = []
        for table_config in config.tables:
            self.stdout.write(f"Listing {table_config.table} files in s3://{table_config.location.bucket}...")
            try:
                files = list_files(table_config)
            except Exception as error:
                raise CommandError(f"Failed to list {table_config.table} files: {error}")
            if not files:
                self.stdout.write(
                    self.style.WARNING(
                        f"  No {table_config.file_format} files found for {table_config.table} "
                        f"under prefix {table_config.location.prefix!r}"
                    )
                )
            plans.append(TablePlan(config=table_config, files=files))
        return plans

    def _print_plan_report(self, config: BootstrapConfig, plans: list[TablePlan]) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Import plan"))
        self.stdout.write(f"  Project: {config.project_name}")
        self.stdout.write(f"  Owner:   {config.email}")
        self.stdout.write("")
        for plan in plans:
            location = plan.config.location
            compression = plan.config.compression or "none"
            self.stdout.write(self.style.MIGRATE_LABEL(f"  {plan.config.table}"))
            self.stdout.write(f"    Source:      s3://{location.bucket}/{location.prefix}")
            self.stdout.write(f"    Format:      {plan.config.file_format} ({compression})")
            self.stdout.write(f"    Files:       {plan.file_count}")
            self.stdout.write(f"    Total size:  {_format_bytes(plan.total_size_bytes)}")

    def _progress(self) -> Progress:
        is_tty = bool(getattr(self.stdout, "isatty", lambda: False)())

        def on_file(table: str, discovered: DiscoveredFile, index: int, total: int) -> None:
            self.stdout.write(
                f"\n  {table}: reading file {index + 1}/{total} "
                f"({_format_bytes(discovered.size_bytes)}) {discovered.key}"
            )

        def on_rows(table: str, total: int) -> None:
            message = f"  {table}: {total:,} rows imported"
            if is_tty:
                self.stdout.write(f"\r{message}", ending="")
                self.stdout.flush()
            else:
                self.stdout.write(message)

        return Progress(on_file=on_file, on_rows=on_rows)

    def _print_final_report(self, report) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Import complete"))
        self.stdout.write(f"  Project: {report.project_name} (team id {report.team_id})")
        self.stdout.write(
            f"  Owner:   {report.email} ({'created' if report.created_user else 'existing user, new project'})"
        )
        for result in report.results:
            line = f"  {result.table}: {result.rows_imported:,} rows"
            if result.table == "persons":
                line += f", {result.distinct_ids_imported:,} distinct ids"
            self.stdout.write(self.style.SUCCESS(line))
        self.stdout.write("")
        self.stdout.write(f"  Log in at http://localhost:8010 with {report.email} / the password you set.")

    def _prompt(self, label: str) -> str:
        value = input(f"{label}: ").strip()
        if not value:
            raise CommandError(f"{label} is required")
        return value

    def _confirm(self, question: str) -> bool:
        answer = input(f"{question} [y/N]: ").strip().lower()
        return answer in ("y", "yes")
