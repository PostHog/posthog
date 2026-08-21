"""Report hog functions whose stored secret is the read-back mask instead of a real credential.

Read-only. It names the affected organizations so operators can ask each owner to re-enter the
credential, which is the only way back: the original value was overwritten, not archived.

Use `--format csv` for a list to work through, and `--max-results 0` to lift the cap when the
run is a full audit rather than a spot check.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.cdp.backend.services.masked_secrets import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_RESULTS,
    findings_as_csv,
    scan_for_masked_secrets,
    summarize_by_organization,
)


class Command(BaseCommand):
    help = (
        "Find hog functions storing the secret mask instead of a real credential, and report the "
        "organizations to contact. Read-only."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--team-ids",
            nargs="+",
            type=int,
            default=None,
            help="Restrict to specific teams. Default: every team.",
        )
        parser.add_argument(
            "--include-deleted",
            action="store_true",
            help="Include soft-deleted hog functions. They send nothing, so they are off by default.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Rows fetched per database round trip (default {DEFAULT_BATCH_SIZE}).",
        )
        parser.add_argument(
            "--max-results",
            type=int,
            default=DEFAULT_MAX_RESULTS,
            help=f"Cap on reported hog functions (default {DEFAULT_MAX_RESULTS}). Pass 0 for no cap.",
        )
        parser.add_argument(
            "--format",
            choices=("text", "csv"),
            default="text",
            help="Default: text. Use csv to pipe the findings somewhere else.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        batch_size = options["batch_size"]
        if batch_size < 1:
            raise CommandError("--batch-size must be at least 1")
        max_results = options["max_results"]
        if max_results < 0:
            raise CommandError("--max-results must be 0 or more")

        scan = scan_for_masked_secrets(
            team_ids=options["team_ids"],
            include_deleted=options["include_deleted"],
            batch_size=batch_size,
            max_results=max_results or None,
        )

        if options["format"] == "csv":
            self.stdout.write(findings_as_csv(scan.findings))
        else:
            self._write_text_report(scan.findings)

        self.stdout.write(
            f"Scanned {scan.scanned_count} hog function(s) with stored secrets. "
            f"Found {len(scan.findings)} storing the mask."
        )
        if scan.truncated:
            self.stdout.write(
                self.style.WARNING(
                    f"Stopped at the --max-results cap of {max_results}. There are more affected hog functions "
                    "than this run reported. Raise the cap or narrow with --team-ids."
                )
            )

    def _write_text_report(self, findings: tuple[Any, ...]) -> None:
        for finding in findings:
            inputs = ", ".join(finding.masked_live_inputs) or "-"
            drafts = ", ".join(finding.masked_draft_inputs)
            draft_note = f" draft_inputs=[{drafts}]" if drafts else ""
            self.stdout.write(
                f"team={finding.team_id} org={finding.organization_id} "
                f"function={finding.hog_function_id} template={finding.template_id or '-'} "
                f"enabled={finding.enabled} inputs=[{inputs}]{draft_note}"
            )

        summaries = summarize_by_organization(findings)
        if not summaries:
            return

        self.stdout.write("")
        self.stdout.write(f"Affected organizations ({len(summaries)}):")
        for summary in summaries:
            self.stdout.write(
                f"  {summary.organization_id} {summary.organization_name} "
                f"teams={list(summary.team_ids)} functions={summary.hog_function_count} "
                f"enabled={summary.enabled_hog_function_count}"
            )
