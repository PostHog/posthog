import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.timezone import now

import structlog

from posthog.models.experiment import Experiment

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Fix experiments where parameters.feature_flag_variants doesn't match the linked feature flag's variants"

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="Actually apply changes. Default is dry-run.")
        parser.add_argument("--team-id", type=int, help="Only fix experiments for a specific team.")

    def handle(self, *args, **options):
        commit = options["commit"]
        team_id = options.get("team_id")

        # Only look at experiments created in the last 5 months (when bug was introduced)
        cutoff_date = now() - timedelta(days=150)

        experiments = Experiment.objects.filter(
            created_at__gte=cutoff_date,
            deleted=False,
        ).select_related("feature_flag")

        if team_id:
            experiments = experiments.filter(team_id=team_id)

        affected = []
        for experiment in experiments:
            if not experiment.feature_flag:
                continue

            flag_variants = experiment.feature_flag.filters.get("multivariate", {}).get("variants", [])
            param_variants = (experiment.parameters or {}).get("feature_flag_variants", [])

            if flag_variants != param_variants:
                affected.append(
                    {
                        "experiment": experiment,
                        "old_variants": param_variants,
                        "new_variants": flag_variants,
                    }
                )

        if not affected:
            logger.info("No affected experiments found.")
            return

        logger.info(f"Found {len(affected)} affected experiment(s)")

        for item in affected:
            exp = item["experiment"]
            logger.info(
                f"Experiment id={exp.id} name='{exp.name}' team_id={exp.team_id}",
                old_variants=item["old_variants"],
                new_variants=item["new_variants"],
            )

        if not commit:
            logger.info("Dry-run mode. Use --commit to apply changes.")
            return

        with transaction.atomic():
            for item in affected:
                exp = item["experiment"]
                parameters = exp.parameters or {}
                parameters["feature_flag_variants"] = item["new_variants"]
                exp.parameters = parameters
                exp.save(update_fields=["parameters"])
                logger.info(f"Fixed experiment id={exp.id}")

        logger.info(f"Successfully fixed {len(affected)} experiment(s)")
