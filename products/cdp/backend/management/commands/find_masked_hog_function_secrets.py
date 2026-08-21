"""Report hog functions and workflows whose stored secret is a read-back marker, not a credential.

Read-only. It names the affected organizations so operators can ask each owner to re-enter the
credential, which is the only way back: the original value was overwritten, not archived.

Use `--max-results 0` to lift the cap when the run is a full audit rather than a spot check.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.cdp.backend.services.masked_secrets import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_RESULTS,
    scan_for_masked_secrets,
    scan_hog_flows_for_masked_secrets,
    summarize_by_organization,
)


class Command(BaseCommand):
    help = (
        "Find hog functions and workflows storing a secret read-back marker instead of a real "
        "credential, and report the organizations to contact. Read-only."
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
            "--include-archived",
            action="store_true",
            help="Include archived workflows. They send nothing, so they are off by default.",
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
        flow_scan = scan_hog_flows_for_masked_secrets(
            team_ids=options["team_ids"],
            include_archived=options["include_archived"],
            batch_size=batch_size,
            max_results=max_results or None,
        )

        self._write_text_report(scan.findings, flow_scan.findings)

        self.stdout.write(
            f"Scanned {scan.scanned_count} hog function(s) and {flow_scan.scanned_count} workflow(s) with stored "
            f"secrets. Found {len(scan.findings)} hog function(s) and {len(flow_scan.findings)} workflow(s) "
            "storing the mask."
        )
        for name, capped_scan in (("hog functions", scan), ("workflows", flow_scan)):
            if capped_scan.truncated:
                self.stdout.write(
                    self.style.WARNING(
                        f"The {name} scan stopped at the --max-results cap of {max_results}. There are more "
                        "affected than this run reported. Raise the cap or narrow with --team-ids."
                    )
                )

    def _write_text_report(self, findings: tuple[Any, ...], flow_findings: tuple[Any, ...]) -> None:
        for finding in findings:
            inputs = ", ".join(finding.masked_live_inputs) or "-"
            drafts = ", ".join(finding.masked_draft_inputs)
            draft_note = f" draft_inputs=[{drafts}]" if drafts else ""
            self.stdout.write(
                f"team={finding.team_id} org={finding.organization_id} "
                f"function={finding.hog_function_id} template={finding.template_id or '-'} "
                f"enabled={finding.enabled} inputs=[{inputs}]{draft_note}"
            )
        for finding in flow_findings:
            inputs = ", ".join(finding.masked_live_inputs) or "-"
            drafts = ", ".join(finding.masked_draft_inputs)
            draft_note = f" draft_inputs=[{drafts}]" if drafts else ""
            self.stdout.write(
                f"team={finding.team_id} org={finding.organization_id} "
                f"workflow={finding.hog_flow_id} status={finding.status} "
                f"inputs=[{inputs}]{draft_note}"
            )

        summaries = summarize_by_organization([*findings, *flow_findings])
        if not summaries:
            return

        self.stdout.write("")
        self.stdout.write(f"Affected organizations ({len(summaries)}):")
        for summary in summaries:
            self.stdout.write(
                f"  {summary.organization_id} {summary.organization_name} "
                f"teams={list(summary.team_ids)} affected={summary.finding_count} "
                f"enabled={summary.enabled_count}"
            )
