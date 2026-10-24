from datetime import UTC, date, datetime, time, timedelta
from typing import TypedDict, cast
from uuid import UUID

from django.db.models import Count, F, Max, Q, QuerySet, Sum
from django.db.models.functions import TruncDate

from products.data_modeling.backend.models.data_modeling_job import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
)


class EngineUsage(TypedDict):
    engine: DataModelingJobEngine
    runs: int
    measured_runs: int
    read_bytes: int | None
    read_rows: int | None
    cpu_microseconds: int | None
    query_count: int | None


class ModelUsage:
    USAGE_FIELDS = ("runs", "measured_runs", "read_bytes", "read_rows", "cpu_microseconds", "query_count")
    COUNT_USAGE_FIELDS = ("runs", "measured_runs")

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
        measured_filter = Q(usage_updated_at__isnull=False)
        return {
            f"{prefix}runs": Count("id", filter=engine_filter),
            f"{prefix}measured_runs": Count("id", filter=engine_filter & measured_filter),
            f"{prefix}read_bytes": Sum("read_bytes", filter=engine_filter),
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
    def engine_usage(cls, row: dict[str, object], engines: tuple[DataModelingJobEngine, ...]) -> list[EngineUsage]:
        return [
            EngineUsage(
                engine=engine,
                runs=cast(int, row[f"{engine}_runs"]),
                measured_runs=cast(int, row[f"{engine}_measured_runs"]),
                read_bytes=cast(int | None, row[f"{engine}_read_bytes"]),
                read_rows=cast(int | None, row[f"{engine}_read_rows"]),
                cpu_microseconds=cast(int | None, row[f"{engine}_cpu_microseconds"]),
                query_count=cast(int | None, row[f"{engine}_query_count"]),
            )
            for engine in engines
        ]

    @classmethod
    def empty_usage(cls, prefix: str = "") -> dict[str, int | None]:
        return {f"{prefix}{field}": 0 if field in cls.COUNT_USAGE_FIELDS else None for field in cls.USAGE_FIELDS}

    @classmethod
    def get(
        cls,
        team_id: int,
        saved_query_ids: list[UUID],
        page: int,
        page_size: int,
        start_date: date,
        end_date: date,
        engines: tuple[DataModelingJobEngine, ...],
    ) -> dict[str, object]:
        start = datetime.combine(start_date, time.min, tzinfo=UTC)
        end = datetime.combine(end_date, time.min, tzinfo=UTC)
        range_days = (end_date - start_date).days
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
                    **cls.empty_usage(),
                    **{
                        key: value
                        for selected_engine in engines
                        for key, value in cls.empty_usage(f"{selected_engine}_").items()
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
    start_date: date,
    end_date: date,
    engines: tuple[DataModelingJobEngine, ...],
) -> dict[str, object]:
    return ModelUsage.get(
        team_id=team_id,
        saved_query_ids=saved_query_ids,
        page=page,
        page_size=page_size,
        start_date=start_date,
        end_date=end_date,
        engines=engines,
    )
