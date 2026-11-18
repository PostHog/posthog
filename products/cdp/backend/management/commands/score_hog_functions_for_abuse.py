"""Score hog functions for abuse with Jev and print a table, to tune the shadow thresholds offline.

Scores enabled functions unless asked with --include-disabled, and ignores the feature flag. Captures no event
unless asked with --capture.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.cdp.backend.abuse import shadow
from products.cdp.backend.abuse.classifier import QUESTIONS


class Command(BaseCommand):
    help = "Score enabled destinations and transformations for abuse with Jev and print the scores."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--id", dest="ids", action="append", default=[], help="A hog function ID. Repeatable.")
        parser.add_argument("--team-id", type=int, help="Score every enabled destination and transformation of a team.")
        parser.add_argument("--capture", action="store_true", help="Also capture each verdict as an event.")
        parser.add_argument(
            "--include-disabled",
            action="store_true",
            help="Also score disabled functions, such as ones turned off after abuse, without enabling them.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not options["ids"] and options["team_id"] is None:
            raise CommandError("Give --id or --team-id.")
        hog_functions = shadow.scorable_hog_functions(enabled_only=not options["include_disabled"])
        hog_functions = (
            hog_functions.filter(id__in=options["ids"])
            if options["ids"]
            else hog_functions.filter(team_id=options["team_id"])
        )

        self.stdout.write("\t".join(["hog_function_id", "type", "template_id", "verdict", "risk", "rules", *QUESTIONS]))
        for hog_function in hog_functions.order_by("team_id", "created_at"):
            if not shadow.runs_customer_code(hog_function):
                continue
            scored = shadow.score(hog_function)
            if options["capture"]:
                shadow.report(hog_function, scored, trigger=shadow.Trigger.EVAL)
            row = [
                str(hog_function.id),
                hog_function.type or "",
                hog_function.template_id or "-",
                *self._columns(scored),
            ]
            self.stdout.write("\t".join(row))

    def _columns(self, scored: shadow.ScoredHogFunction) -> list[str]:
        verdict = scored.verdict
        rule_hits = ",".join(scored.rule_hits) or "-"
        if verdict is None:
            return [f"error:{scored.failure}", "-", rule_hits, *("-" for _ in QUESTIONS)]
        return [
            scored.label,
            f"{verdict.risk_score:.2f}",
            rule_hits,
            *(f"{verdict.scores[question]:.2f}" for question in QUESTIONS),
        ]
