from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import TypedDict, cast
from uuid import UUID

from django.db.models import Count, F, Max, Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce, Lower, NullIf, TruncDate

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


class ModelStatusModel(TypedDict):
    saved_query_id: UUID
    name: str
    deleted: bool


class ModelStatusBreakdown(TypedDict):
    engine: DataModelingJobEngine
    status: DataModelingJobStatus
    count: int
    models: list[ModelStatusModel]


class ModelUsage:
    USAGE_FIELDS = ("runs", "measured_runs", "read_bytes", "read_rows", "cpu_microseconds", "query_count")
    COUNT_USAGE_FIELDS = ("runs", "measured_runs")

    @staticmethod
    def all_jobs(
        team_id: int, start: datetime, end: datetime, engines: tuple[DataModelingJobEngine, ...]
    ) -> QuerySet[DataModelingJob]:
        return DataModelingJob.objects.filter(
            team_id=team_id,
            engine__in=engines,
            last_run_at__gte=start,
            last_run_at__lt=end,
        )

    @classmethod
    def jobs(
        cls, team_id: int, start: datetime, end: datetime, engines: tuple[DataModelingJobEngine, ...]
    ) -> QuerySet[DataModelingJob]:
        return cls.all_jobs(team_id, start, end, engines).filter(
            status__in=[DataModelingJobStatus.COMPLETED, DataModelingJobStatus.FAILED, DataModelingJobStatus.CANCELLED]
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
    def engine_usage(cls, row: Mapping[str, object], engines: tuple[DataModelingJobEngine, ...]) -> list[EngineUsage]:
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

    @staticmethod
    def status_breakdown(jobs: QuerySet[DataModelingJob]) -> list[ModelStatusBreakdown]:
        latest_jobs = (
            jobs.filter(saved_query_id__isnull=False)
            .select_related("saved_query")
            .only("saved_query_id", "engine", "status", "saved_query__name", "saved_query__deleted")
            .order_by("saved_query_id", "engine", "-last_run_at", "-created_at")
            .distinct("saved_query_id", "engine")
        )
        groups: dict[tuple[DataModelingJobEngine, DataModelingJobStatus], list[ModelStatusModel]] = {}
        for job in latest_jobs:
            if job.saved_query is None or job.saved_query_id is None:
                continue
            key = (DataModelingJobEngine(job.engine), DataModelingJobStatus(job.status))
            groups.setdefault(key, []).append(
                ModelStatusModel(
                    saved_query_id=job.saved_query_id,
                    name=job.saved_query.name or "Untitled model",
                    deleted=job.saved_query.deleted is not False,
                )
            )

        for models in groups.values():
            models.sort(key=lambda model: (model["name"].lower(), str(model["saved_query_id"])))

        return [
            ModelStatusBreakdown(engine=engine, status=status, count=len(models), models=models)
            for (engine, status), models in sorted(groups.items())
        ]

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
        sort_by: str = "read_bytes",
        sort_direction: str = "desc",
    ) -> dict[str, object]:
        start = datetime.combine(start_date, time.min, tzinfo=UTC)
        end = datetime.combine(end_date, time.min, tzinfo=UTC)
        range_days = (end_date - start_date).days
        jobs = cls.jobs(team_id, start, end, engines).filter(saved_query_id__in=saved_query_ids)
        status_jobs = cls.all_jobs(team_id, start, end, engines).filter(saved_query_id__in=saved_query_ids)
        overview = jobs.aggregate(**cls.aggregates())
        usage_updated_at = jobs.aggregate(latest=Max("usage_updated_at"))["latest"]
        daily: dict[date, Mapping[str, object]] = {
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
            **cls.engine_aggregates((DataModelingJobEngine.CLICKHOUSE, DataModelingJobEngine.MANAGED_WAREHOUSE)),
            **cls.aggregates(),
        )
        count = models.count()
        offset = (page - 1) * page_size
        sort_expression = (
            Lower(Coalesce(NullIf("saved_query__name", Value("")), Value("Deleted model")))
            if sort_by == "name"
            else F(sort_by)
        )
        ordering = (
            sort_expression.asc(nulls_last=True) if sort_direction == "asc" else sort_expression.desc(nulls_last=True)
        )
        rows: list[Mapping[str, object]] = list(
            models.order_by(ordering, "saved_query_id")[offset : offset + page_size]
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
            "status_breakdown": cls.status_breakdown(status_jobs),
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
    sort_by: str = "read_bytes",
    sort_direction: str = "desc",
) -> dict[str, object]:
    return ModelUsage.get(
        team_id=team_id,
        saved_query_ids=saved_query_ids,
        page=page,
        page_size=page_size,
        start_date=start_date,
        end_date=end_date,
        engines=engines,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )
