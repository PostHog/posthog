import logging
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from posthog.tasks.email import send_hog_function_filters_uncompilable

from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionType

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Find enabled hog functions that have no filter bytecode because their filters failed to "
        "compile, and tell their project. A function in this state matches nothing and delivers "
        "nothing, because evaluating a null bytecode raises on every event. A function that kept "
        "its last working bytecode carries the same error but still delivers, so it is left alone."
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

        # The error alone does not identify the dead state, because a save that fails to recompile
        # keeps the last working bytecode beside the error and that function still delivers. Both
        # shapes of "no bytecode" are selected: the key is absent on a function that has never
        # compiled, and JSON null on one whose bytecode was cleared. Matching on the error message
        # would miss the compile failures that are not about cohorts.
        # Destinations only. Transformations, source webhooks and internal destinations compile
        # bytecode too and can carry the same error, but the email names a destination and links to
        # the destinations page, and an internal destination is ours rather than the customer's.
        queryset = (
            HogFunction.objects.filter(deleted=False, enabled=True, type=HogFunctionType.DESTINATION)
            .exclude(filters__bytecode_error__isnull=True)
            .filter(Q(filters__bytecode__isnull=True) | Q(filters__bytecode=None))
        )
        team_id = options["team_id"]
        if team_id is not None:
            # `if team_id:` would read a mistyped 0 as "every team" and hand the whole fleet to
            # --apply. No team has id 0, so the filter reports nothing instead.
            queryset = queryset.filter(team_id=team_id)
        queryset = queryset.select_related("team", "created_by").order_by("team_id", "id")
        limit = options["limit"]
        if limit is not None:
            # `if limit:` would read 0 as "no limit" and hand the whole fleet to --apply, and a
            # negative value raises inside the slice.
            if limit < 1:
                raise CommandError("--limit must be 1 or more")
            queryset = queryset[:limit]

        # Collected first so nothing is written while the queryset is still being walked.
        by_team: dict[int, list[HogFunction]] = {}
        for hog_function in queryset:
            by_team.setdefault(hog_function.team_id, []).append(hog_function)
            error = (hog_function.filters or {}).get("bytecode_error", "")
            self.stdout.write(
                f"team={hog_function.team_id} id={hog_function.id} type={hog_function.type} "
                f"name={hog_function.name!r} error={error!r}"
            )

        count = sum(len(functions) for functions in by_team.values())
        self.stdout.write("")

        # One team at a time, and the email for a team goes out right after that team's writes.
        # A broker or database failure part way through therefore leaves later teams untouched,
        # and the line printed per team says how far the run got.
        #
        # The gap this does not close: a send that fails after the disable leaves that team's
        # destinations off and unnotified, and a plain re-run will not find them because the scope
        # is enabled destinations. Re-enable them and re-run with --team-id.
        for team_id, functions in sorted(by_team.items()):
            if apply and disable:
                for hog_function in functions:
                    hog_function.enabled = False
                    # save() rather than a queryset update: the post_save receiver is what tells
                    # the workers to reload, and without it the destination stays live in their
                    # cache. The cost is that save() recompiles the filters, which fails again and
                    # rewrites the same bytecode_error. That is wasted work, not a wrong result.
                    hog_function.save(update_fields=["enabled"])

            if apply:
                # One email per project. A shared mistake breaks many destinations at once, so a
                # task per destination would mail the same admins the same root cause repeatedly.
                send_hog_function_filters_uncompilable.delay(team_id, [str(f.id) for f in functions])

            self.stdout.write(f"team={team_id}: {len(functions)} destination(s)" + (" queued" if apply else ""))

        self.stdout.write("")
        self.stdout.write(f"{count} enabled destination(s) with uncompilable filters across {len(by_team)} team(s)")
        if not apply:
            self.stdout.write("Dry run. Re-run with --apply to send the emails.")
        elif disable:
            self.stdout.write("Disabled each destination and emailed each project's admins and creators.")
        else:
            self.stdout.write("Emailed each project's admins and creators.")
