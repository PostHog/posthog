import logging
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand

from posthog.tasks.email import send_hog_function_filters_uncompilable

from products.cdp.backend.models.hog_functions.hog_function import HogFunction

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Find enabled hog functions whose filters failed to compile, and tell their project. "
        "A function in this state matches nothing and delivers nothing, because the filter "
        "bytecode is null and evaluating it raises on every event."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Send the emails. Without this the command only prints what it would do.",
        )
        parser.add_argument(
            "--disable",
            action="store_true",
            help=(
                "Also set enabled=false on each function. Off by default: the function already "
                "delivers nothing, and disabling means the owner has to re-enable it after fixing."
            ),
        )
        parser.add_argument("--team-id", type=int, help="Limit to one team.")
        parser.add_argument("--limit", type=int, help="Stop after this many functions.")

    def handle(self, *args: Any, **options: Any) -> None:
        apply: bool = options["apply"]
        disable: bool = options["disable"]

        # `bytecode` is set to null alongside every bytecode_error, so the error alone identifies
        # the state. Matching on the message would miss the compile failures that are not about
        # cohorts.
        queryset = HogFunction.objects.filter(deleted=False, enabled=True).exclude(filters__bytecode_error__isnull=True)
        if options["team_id"]:
            queryset = queryset.filter(team_id=options["team_id"])
        queryset = queryset.select_related("team", "created_by").order_by("team_id", "id")
        if options["limit"]:
            queryset = queryset[: options["limit"]]

        count = 0
        by_team: dict[int, int] = {}
        for hog_function in queryset:
            count += 1
            by_team[hog_function.team_id] = by_team.get(hog_function.team_id, 0) + 1
            error = (hog_function.filters or {}).get("bytecode_error", "")
            self.stdout.write(
                f"team={hog_function.team_id} id={hog_function.id} type={hog_function.type} "
                f"name={hog_function.name!r} error={error!r}"
            )

            if not apply:
                continue

            if disable:
                hog_function.enabled = False
                # save() rather than a queryset update: the post_save receiver is what tells the
                # workers to reload, and without it the function stays live in their cache. The
                # cost is that save() recompiles the filters, which fails again and rewrites the
                # same bytecode_error. That is wasted work, not a wrong result.
                hog_function.save(update_fields=["enabled"])
            send_hog_function_filters_uncompilable.delay(str(hog_function.id))

        self.stdout.write("")
        self.stdout.write(f"{count} enabled function(s) with uncompilable filters across {len(by_team)} team(s)")
        if not apply:
            self.stdout.write("Dry run. Re-run with --apply to send the emails.")
        elif disable:
            self.stdout.write("Disabled each function and queued an email to its project admins and creator.")
        else:
            self.stdout.write("Queued an email to each function's project admins and creator.")
