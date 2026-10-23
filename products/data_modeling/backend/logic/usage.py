from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from django.db.models import Count, F, Max, Q, QuerySet, Sum
from django.db.models.functions import TruncDate

from products.data_modeling.backend.models.data_modeling_job import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
)


class ModelUsage:
    @staticmethod
    def jobs(team_id: int, start: datetime, end: datetime) -> QuerySet[DataModelingJob]:
        return DataModelingJob.objects.filter(
            team_id=team_id,
            engine=DataModelingJobEngine.CLICKHOUSE,
            status__in=[DataModelingJobStatus.COMPLETED, DataModelingJobStatus.FAILED, DataModelingJobStatus.CANCELLED],
            last_run_at__gte=start,
            last_run_at__lt=end,
        )

    @staticmethod
    def aggregates() -> dict[str, Count | Sum]:
        return {
            "runs": Count("id"),
            "measured_runs": Count("id", filter=Q(usage_updated_at__isnull=False)),
            "read_bytes": Sum("read_bytes"),
            "read_rows": Sum("read_rows"),
            "cpu_microseconds": Sum("cpu_microseconds"),
            "query_count": Sum("query_count"),
        }

    @classmethod
    def get(cls, team_id: int, saved_query_ids: list[UUID], days: int, page: int, page_size: int) -> dict[str, object]:
        end = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
        start = end - timedelta(days=days)
        jobs = cls.jobs(team_id, start, end).filter(saved_query_id__in=saved_query_ids)
        overview = jobs.aggregate(**cls.aggregates())
        usage_updated_at = jobs.aggregate(latest=Max("usage_updated_at"))["latest"]
        daily = {
            row["day"]: row
            for row in jobs.annotate(day=TruncDate("last_run_at", tzinfo=UTC))
            .values("day")
            .annotate(**cls.aggregates())
            .order_by("day")
        }
        trends = []
        for offset in range(days):
            day: date = (start + timedelta(days=offset)).date()
            trends.append(
                daily.get(
                    day,
                    {
                        "day": day,
                        "runs": 0,
                        "measured_runs": 0,
                        "read_bytes": None,
                        "read_rows": None,
                        "cpu_microseconds": None,
                        "query_count": None,
                    },
                )
            )
        models = jobs.values("saved_query_id", "saved_query__name", "saved_query__deleted").annotate(**cls.aggregates())
        count = models.count()
        offset = (page - 1) * page_size
        rows = list(
            models.order_by(F("read_bytes").desc(nulls_last=True), "saved_query_id")[offset : offset + page_size]
        )
        return {
            "date_from": start.date(),
            "date_to": end.date(),
            "overview": overview,
            "trends": trends,
            "models": [
                {
                    "saved_query_id": row["saved_query_id"],
                    "name": row["saved_query__name"] or "Deleted model",
                    "deleted": row["saved_query__deleted"] is not False,
                    **{key: row[key] for key in cls.aggregates()},
                }
                for row in rows
            ],
            "count": count,
            "usage_updated_at": usage_updated_at,
        }


def get_model_usage(
    team_id: int, saved_query_ids: list[UUID], days: int, page: int, page_size: int
) -> dict[str, object]:
    return ModelUsage.get(team_id, saved_query_ids, days, page, page_size)
