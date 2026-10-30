from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

from posthog.clickhouse.query_tagging import Product

if TYPE_CHECKING:
    from django.db import models

DEFAULT_MAX_ROWS_PER_DAY = 2_000_000


class DailyRollup:
    """One Postgres table that holds one row per natural key per UTC day, filled from ClickHouse.

    A Dagster job built with `build_daily_rollup_job` fills a day by running `fill_sql()` once per
    team id range, and replaces the day in Postgres in one transaction.

    `fill_sql()` returns the table's columns in `columns` order, without `day`, which the framework
    adds. It must filter on `%(team_id_start)s <= team_id < %(team_id_end)s` and on
    `%(day_start)s <= timestamp < %(day_end)s`. `columns` must include `event_count`.
    """

    model: ClassVar[type[models.Model]]
    product: ClassVar[Product | None] = None
    columns: ClassVar[tuple[str, ...]]
    retention_days: ClassVar[int]
    max_rows_per_day: ClassVar[int] = DEFAULT_MAX_ROWS_PER_DAY

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "model" not in cls.__dict__:
            return
        if cls.columns[:2] != ("team_id", "day"):
            raise ValueError(f"{cls.__name__}.columns must start with team_id and day")
        if "event_count" not in cls.columns:
            raise ValueError(f"{cls.__name__}.columns must include event_count")

    @classmethod
    def table(cls) -> str:
        return cls.model._meta.db_table

    @classmethod
    def fill_sql(cls) -> str:
        raise NotImplementedError

    @classmethod
    def fill_params(cls) -> Mapping[str, Any]:
        """Extra ClickHouse parameters for `fill_sql()`, such as an allowlist."""
        return {}
