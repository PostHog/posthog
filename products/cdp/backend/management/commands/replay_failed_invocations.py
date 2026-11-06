"""Replay destination and workflow invocations that failed during an incident.

Prints the plan by default and sends nothing. To send, pass --execute together
with --fingerprint set to the value the preview printed. The command computes
the plan again before it sends, and refuses when the fingerprint no longer
matches, so it never sends a set of invocations that nobody previewed.

The same flow is available in Django admin, on the hog function list page.
"""

from datetime import UTC, datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.cdp.backend.services.invocation_replay import (
    DEFAULT_LATEST_PER_PERSON_TEMPLATE_IDS,
    SKIP_REASON_LABELS,
    ReplayCriteria,
    ReplayOverlapError,
    claim_replay,
    execute_replay,
    is_replay_claimed,
    plan_replay,
    release_replay_claim,
)


def _parse_datetime(value: str, flag: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CommandError(f"{flag} must be an ISO-8601 timestamp with a timezone") from error
    if parsed.tzinfo is None:
        raise CommandError(f"{flag} must include a timezone, e.g. 2026-10-22T11:30:00Z")
    # The rerun worker drops the offset of the window it receives, so the plan and the send must both use UTC.
    return parsed.astimezone(UTC)


class Command(BaseCommand):
    help = "Replay failed destination invocations from an incident window. Prints the plan unless --execute is set."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--window-start", required=True, help="Inclusive ISO-8601 UTC timestamp.")
        parser.add_argument("--window-end", required=True, help="Exclusive ISO-8601 UTC timestamp.")
        parser.add_argument(
            "--error-message-contains", default="", help='Case-insensitive substring of the error, e.g. "401".'
        )
        parser.add_argument("--error-kind", action="append", default=[], dest="error_kinds", help="Repeatable.")
        parser.add_argument("--team-id", action="append", type=int, default=[], dest="team_ids", help="Repeatable.")
        parser.add_argument("--template-id", action="append", default=[], dest="template_ids", help="Repeatable.")
        parser.add_argument(
            "--exclude-template-id", action="append", default=[], dest="exclude_template_ids", help="Repeatable."
        )
        parser.add_argument(
            "--latest-per-person-template-id",
            action="append",
            default=None,
            dest="latest_per_person_template_ids",
            help=f"Repeatable. Default: {', '.join(DEFAULT_LATEST_PER_PERSON_TEMPLATE_IDS)}.",
        )
        parser.add_argument(
            "--include-functions-without-recent-success",
            action="store_true",
            help="Also replay functions that have not succeeded since the window ended.",
        )
        parser.add_argument("--include-already-rerun", action="store_true", help="Also replay runs re-run before.")
        parser.add_argument(
            "--include-functions-failing-before-window",
            action="store_true",
            help="Also replay functions that already failed the same way in the day before the window.",
        )
        parser.add_argument(
            "--include-workflows",
            action="store_true",
            help="Also replay workflow runs that stopped on a failed step. Each run continues from that step.",
        )
        parser.add_argument("--details", action="store_true", help="Print one line per function.")
        parser.add_argument("--execute", action="store_true", help="Send the replay. Requires --fingerprint.")
        parser.add_argument("--fingerprint", default="", help="The fingerprint printed by the preview.")
        parser.add_argument(
            "--allow-resend",
            action="store_true",
            help="With --execute, send a plan again that was sent before. Use only after checking that its runs were not queued.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        latest_per_person = options["latest_per_person_template_ids"]
        try:
            criteria = ReplayCriteria(
                window_start=_parse_datetime(options["window_start"], "--window-start"),
                window_end=_parse_datetime(options["window_end"], "--window-end"),
                error_message_contains=options["error_message_contains"],
                error_kinds=tuple(options["error_kinds"]),
                team_ids=tuple(options["team_ids"]),
                template_ids=tuple(options["template_ids"]),
                exclude_template_ids=tuple(options["exclude_template_ids"]),
                latest_per_person_template_ids=tuple(
                    DEFAULT_LATEST_PER_PERSON_TEMPLATE_IDS if latest_per_person is None else latest_per_person
                ),
                require_success_since_window=not options["include_functions_without_recent_success"],
                skip_already_rerun=not options["include_already_rerun"],
                skip_failing_before_window=not options["include_functions_failing_before_window"],
                include_workflows=options["include_workflows"],
            )
        except ValueError as error:
            raise CommandError(str(error)) from error

        plan = plan_replay(criteria)

        self.stdout.write(
            f"{plan.invocation_count} invocation(s) to replay across "
            f"{len(plan.replayable_functions)} destination(s) or workflow(s) in {plan.team_count} team(s)."
        )
        for template_id, count in plan.invocations_by_template.items():
            self.stdout.write(f"  {template_id or '(no template)'}: {count}")
        for reason, count in plan.skipped.items():
            self.stdout.write(f"  skipped, {SKIP_REASON_LABELS[reason]}: {count}")
        for team in plan.teams:
            self.stdout.write(
                f"  team {team.team_id} ({team.team_name}): {team.invocation_count} in {team.function_count} destination(s) or workflow(s)"
            )
        if options["details"]:
            for function in plan.functions:
                self.stdout.write(
                    f"  {function.function_kind} {function.function_id} team={function.team_id} template={function.template_id} "
                    f"replay={len(function.invocation_ids)} skipped={function.skipped}"
                )
        self.stdout.write(f"Fingerprint: {plan.fingerprint}")

        if not options["execute"]:
            self.stdout.write("Nothing was sent. Re-run with --execute --fingerprint=<fingerprint> to send.")
            return
        if options["fingerprint"] != plan.fingerprint:
            raise CommandError(
                "The plan does not match --fingerprint, so nothing was sent. Review the plan above and use its fingerprint."
            )

        if options["allow_resend"] and not release_replay_claim(plan.fingerprint, actor="management_command"):
            raise CommandError("This plan is not blocked, or it is still being sent, so nothing was sent.")
        try:
            claimed = claim_replay(plan, actor="management_command")
        except ReplayOverlapError as error:
            raise CommandError(f"{error} Nothing was sent.") from error
        if claimed is None:
            raise CommandError("This plan was already sent, so nothing was sent again.")
        results = execute_replay(plan, actor="management_command")
        for result in results:
            self.stdout.write(
                f"  team {result.team_id} function {result.function_id}: {result.invocation_count} "
                f"-> HTTP {result.status_code} {result.detail[:200]}"
            )
        failed = [r for r in results if r.status_code != 200]
        self.stdout.write(f"Sent {len(results) - len(failed)} request(s), {len(failed)} failed.")
        if failed and is_replay_claimed(plan.fingerprint):
            raise CommandError(
                f"{len(failed)} request(s) failed, and some may still have queued their runs, so this plan stays blocked. "
                "Check the runs on the destinations. If nothing was queued, send again with --allow-resend."
            )
        if failed:
            raise CommandError(
                f"{len(failed)} request(s) failed. Preview again to see the runs that are still failed, then send that plan."
            )
