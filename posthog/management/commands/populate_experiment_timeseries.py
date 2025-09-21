import traceback
from datetime import date, datetime, timedelta
from typing import Union
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.utils import timezone

from posthog.schema import ExperimentFunnelMetric, ExperimentMeanMetric, ExperimentQuery, ExperimentRatioMetric

from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.models.experiment import Experiment, ExperimentMetricResult


class Command(BaseCommand):
    help = "Populate ExperimentMetricResult records for testing experiment timeseries functionality"

    def add_arguments(self, parser):
        parser.add_argument(
            "--experiment-id",
            type=int,
            required=True,
            help="Experiment ID to populate timeseries data for",
        )
        parser.add_argument(
            "--metric-uuid",
            type=str,
            required=True,
            help="Metric UUID to populate data for",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force recalculation of existing records",
        )

    def handle(self, *args, **options):
        experiment_id = options["experiment_id"]
        metric_uuid = options["metric_uuid"]
        force = options["force"]

        try:
            self.populate_timeseries(
                experiment_id=experiment_id,
                metric_uuid=metric_uuid,
                force=force,
            )
        except Exception as e:
            error_msg = f"Error populating experiment timeseries: {e}\n\nFull traceback:\n{traceback.format_exc()}"
            self.stdout.write(self.style.ERROR(error_msg))

    def populate_timeseries(self, experiment_id: int, metric_uuid: str, force: bool) -> None:
        """
        Populate ExperimentMetricResult records for the entire experiment duration using real calculations
        """
        try:
            experiment = Experiment.objects.get(id=experiment_id, deleted=False)
        except Experiment.DoesNotExist:
            raise ValueError(f"Experiment {experiment_id} not found or deleted")

        all_metrics = (experiment.metrics or []) + (experiment.metrics_secondary or [])
        metric = next((m for m in all_metrics if m.get("uuid") == metric_uuid), None)
        if not metric:
            raise ValueError(f"Metric {metric_uuid} not found in experiment {experiment_id}")

        metric_type = metric.get("metric_type")
        metric_obj: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]
        if metric_type == "mean":
            metric_obj = ExperimentMeanMetric(**metric)
        elif metric_type == "funnel":
            metric_obj = ExperimentFunnelMetric(**metric)
        elif metric_type == "ratio":
            metric_obj = ExperimentRatioMetric(**metric)
        else:
            raise ValueError(f"Unknown metric type: {metric_type}")

        # Determine project timezone for display purposes
        project_tz = ZoneInfo(experiment.team.timezone) if experiment.team.timezone else ZoneInfo("UTC")
        utc_tz = ZoneInfo("UTC")

        start_date = experiment.start_date.date() if experiment.start_date else experiment.created_at.date()
        end_date = experiment.end_date.date() if experiment.end_date else date.today()

        self.stdout.write(f"Populating timeseries for experiment {experiment_id} ({experiment.name})")
        self.stdout.write(f"Metric: {metric.get('name', metric_uuid)}")
        self.stdout.write(f"Date range: {start_date} to {end_date}")
        self.stdout.write(f"Project timezone: {project_tz}")

        experiment_dates = []
        current_date = start_date
        while current_date <= end_date:
            experiment_dates.append(current_date)
            current_date += timedelta(days=1)

        self.stdout.write(f"Total days: {len(experiment_dates)}")

        created_count = 0
        updated_count = 0
        skipped_count = 0

        for experiment_date in experiment_dates:
            # For backfilling, use 2am UTC (consistent with daily recalculation schedule at "0 2 * * *")
            # This ensures backfilled data matches what would be calculated by the daily schedule
            query_to_utc = datetime.combine(experiment_date, datetime.min.time().replace(hour=2), tzinfo=utc_tz)

            # Cumulative calculation: always from experiment start to the query time
            query_from_utc = experiment.start_date if experiment.start_date else experiment.created_at

            if (
                not force
                and ExperimentMetricResult.objects.filter(
                    experiment_id=experiment_id, metric_uuid=metric_uuid, query_to=query_to_utc
                ).exists()
            ):
                skipped_count += 1
                continue

            self.stdout.write(f"Calculating for {experiment_date} (up to {query_to_utc.strftime('%H:%M %Z')})...")

            status = "completed"
            result_data = None
            completed_at = None
            error_message = None

            try:
                experiment_query = ExperimentQuery(
                    experiment_id=experiment_id,
                    metric=metric_obj,
                )

                # Use query_to_utc as the override end date for the query runner
                query_runner = ExperimentQueryRunner(
                    query=experiment_query, team=experiment.team, override_end_date=query_to_utc
                )
                result = query_runner._calculate()
                result_data = result.model_dump()

                # Record when the calculation actually completed
                completed_at = timezone.now()

            except Exception as e:
                status = "failed"
                error_message = str(e)
                completed_at = None  # Never completed
                self.stdout.write(self.style.WARNING(f"  Failed: {error_message}"))

            metric_result, created = ExperimentMetricResult.objects.update_or_create(
                experiment_id=experiment_id,
                metric_uuid=metric_uuid,
                query_to=query_to_utc,
                defaults={
                    "query_from": query_from_utc,
                    "status": status,
                    "result": result_data,
                    "query_id": None,
                    "completed_at": completed_at,
                    "error_message": error_message,
                },
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully populated timeseries data:\n"
                f"  Created: {created_count} records\n"
                f"  Updated: {updated_count} records\n"
                f"  Skipped: {skipped_count} records\n"
                f"  Total: {len(experiment_dates)} days"
            )
        )
