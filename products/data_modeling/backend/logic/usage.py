from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from django.db.models import Case, Count, F, Max, Q, QuerySet, Sum, When
from django.db.models.functions import TruncDate

from products.data_modeling.backend.models.data_modeling_job import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
)


class ModelUsage:
    ENGINES = (DataModelingJobEngine.CLICKHOUSE, DataModelingJobEngine.MANAGED_WAREHOUSE)
    USAGE_FIELDS = ("runs", "measured_runs", "read_bytes", "read_rows", "cpu_microseconds", "query_count")

    @staticmethod
    def jobs(
        team_id: int, start: datetime, end: datetime, engines: tuple[DataModelingJobEngine, ...]
    ) -> QuerySet[DataModelingJob]:
        return DataModelingJob.objects.filter(
            team_id=team_id,
            engine__in=engines,
            status__in=[DataModelingJobStatus.COMPLETED, DataModelingJobStatus.FAILED, DataModelingJobStatus.CANCELLED],
            last_run_at__gte=start,
            last_run_at__lt=end,
        )

    @staticmethod
    def aggregates(*, prefix: str = "", engine: DataModelingJobEngine | None = None) -> dict[str, Count | Sum]:
        engine_filter = Q(engine=engine) if engine else Q()
        measured_filter = Q(usage_updated_at__isnull=False) | Q(
            engine=DataModelingJobEngine.MANAGED_WAREHOUSE, bytes_read__isnull=False
        )
        normalized_read_bytes = Case(
            When(engine=DataModelingJobEngine.MANAGED_WAREHOUSE, then=F("bytes_read")),
            default=F("read_bytes"),
        )
        return {
            f"{prefix}runs": Count("id", filter=engine_filter),
            f"{prefix}measured_runs": Count("id", filter=engine_filter & measured_filter),
            f"{prefix}read_bytes": Sum(normalized_read_bytes, filter=engine_filter),
            f"{prefix}read_rows": Sum("read_rows", filter=engine_filter),
            f"{prefix}cpu_microseconds": Sum("cpu_microseconds", filter=engine_filter),
            f"{prefix}query_count": Sum("query_count", filter=engine_filter),
        }

    @classmethod
    def engine_aggregates(cls, engines: tuple[DataModelingJobEngine, ...]) -> dict[str, Count | Sum]:
        return {
            key: aggregate
            for engine in engines
            for key, aggregate in cls.aggregates(prefix=f"{engine}_", engine=engine).items()
        }

    @classmethod
    def engine_usage(cls, row: dict[str, object], engines: tuple[DataModelingJobEngine, ...]) -> list[dict]:
        return [
            {
                "engine": engine,
                **{field: row[f"{engine}_{field}"] for field in cls.USAGE_FIELDS},
            }
            for engine in engines
        ]

    @classmethod
    def get(
        cls,
        team_id: int,
        saved_query_ids: list[UUID],
        page: int,
        page_size: int,
        engine: str,
        days: int | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, object]:
        today = datetime.now(UTC).date()
        end_date = min(date_to + timedelta(days=1) if date_to else today, today)
        start_date = date_from or end_date - timedelta(days=days or 30)
        start = datetime.combine(start_date, time.min, tzinfo=UTC)
        end = datetime.combine(end_date, time.min, tzinfo=UTC)
        range_days = (end_date - start_date).days
        engines = cls.ENGINES if engine == "all" else (DataModelingJobEngine(engine),)
        jobs = cls.jobs(team_id, start, end, engines).filter(saved_query_id__in=saved_query_ids)
        overview = jobs.aggregate(**cls.aggregates())
        usage_updated_at = jobs.aggregate(latest=Max("usage_updated_at"))["latest"]
        daily = {
            row["day"]: row
            for row in jobs.annotate(day=TruncDate("last_run_at", tzinfo=UTC))
            .values("day")
            .annotate(**cls.engine_aggregates(engines), **cls.aggregates())
            .order_by("day")
        }
        trends = []
        for offset in range(range_days):
            day: date = (start + timedelta(days=offset)).date()
            row = daily.get(
                day,
                {
                    "day": day,
                    **{field: 0 if field in ("runs", "measured_runs") else None for field in cls.USAGE_FIELDS},
                    **{
                        f"{selected_engine}_{field}": 0 if field in ("runs", "measured_runs") else None
                        for selected_engine in engines
                        for field in cls.USAGE_FIELDS
                    },
                },
            )
            trends.append(
                {
                    **{field: row[field] for field in ("day", *cls.USAGE_FIELDS)},
                    "engines": cls.engine_usage(row, engines),
                }
            )
        models = jobs.values("saved_query_id", "saved_query__name", "saved_query__deleted").annotate(
            **cls.engine_aggregates(engines), **cls.aggregates()
        )
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
                    **{key: row[key] for key in cls.USAGE_FIELDS},
                    "engines": cls.engine_usage(row, engines),
                }
                for row in rows
            ],
            "count": count,
            "usage_updated_at": usage_updated_at,
        }


def get_model_usage(
    team_id: int,
    saved_query_ids: list[UUID],
    page: int,
    page_size: int,
    engine: str,
    days: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, object]:
    return ModelUsage.get(team_id, saved_query_ids, page, page_size, engine, days, date_from, date_to)
