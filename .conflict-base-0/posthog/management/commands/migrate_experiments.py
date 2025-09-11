import logging
from datetime import datetime

from django.core.management.base import BaseCommand

from posthog.schema import ExperimentFunnelsQuery, ExperimentTrendsQuery

from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.models import Experiment

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Migrate experiment metrics to new schema"

    def handle(self, *args, **options):
        logger.info("Starting experiments migration")

        experiments = Experiment.objects.iterator(chunk_size=100)
        for experiment in experiments:
            try:
                # Check for valid insight type
                if not experiment.filters.get("insight"):
                    logger.warning(f"Skipping experiment {experiment.id}: 'insight' type is missing or invalid")
                    continue

                # Update main metric
                main_experiment_query = self.create_experiment_query(
                    filters=experiment.filters,
                    custom_exposure_filter=(
                        experiment.parameters.get("custom_exposure_filter") if experiment.parameters else None
                    ),
                )
                experiment.metrics = [main_experiment_query.model_dump()]

                # Update secondary metrics
                experiment.metrics_secondary = []
                for secondary_metric in experiment.secondary_metrics:
                    secondary_query = self.create_experiment_query(
                        filters=secondary_metric["filters"],
                        name=secondary_metric["name"],
                    )
                    experiment.metrics_secondary.append(secondary_query.model_dump())

                experiment.filters["migrated_at"] = str(datetime.now())

                experiment.save()
                logger.info(f"ID: {experiment.id} updated")
            except Exception as e:
                capture_exception(e)
                logger.exception(f"Error migrating experiment {experiment.id}")

        logger.info("Experiment migration completed")

    def create_experiment_query(self, filters, custom_exposure_filter=None, name=None):
        filters["explicit_date"] = True

        if filters.get("insight") == "TRENDS":
            count_query = filter_to_query(filters)
            exposure_query = None
            if custom_exposure_filter:
                exposure_query = filter_to_query(custom_exposure_filter)
            return ExperimentTrendsQuery(
                count_query=count_query,
                exposure_query=exposure_query,
                name=name,
            )
        elif filters.get("insight") == "FUNNELS":
            funnels_query = filter_to_query(filters)
            return ExperimentFunnelsQuery(
                funnels_query=funnels_query,
                name=name,
            )
        raise ValueError(f"Unsupported or missing insight type: {filters.get('insight')}")
