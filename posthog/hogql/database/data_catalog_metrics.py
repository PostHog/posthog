from typing import Literal, get_args

from prometheus_client import Counter

CatalogSurface = Literal[
    "metrics",
    "certifications",
    "relationships",
    "relationship_proposals",
    "tables",
    "schema_serialization",
    "table_visibility",
]

DATA_CATALOG_READS_COUNTER = Counter(
    "posthog_data_catalog_reads_total",
    "Data catalog reads attempted, per surface. The denominator for posthog_data_catalog_read_failures_total",
    labelnames=["surface"],
)

DATA_CATALOG_READ_FAILURES_COUNTER = Counter(
    "posthog_data_catalog_read_failures_total",
    "Data catalog reads that failed and fell back to an empty result. The caller sees an empty catalog "
    "rather than an error, so every failure silently hides governed metrics, trust marks, or joins. "
    "Alert on a sustained rate rather than on any single failure: one team's broken definition "
    "increments on every read until it is fixed. The structured log next to each increment carries team_id",
    labelnames=["surface"],
)

for _surface in get_args(CatalogSurface):
    DATA_CATALOG_READS_COUNTER.labels(surface=_surface)
    DATA_CATALOG_READ_FAILURES_COUNTER.labels(surface=_surface)


def record_catalog_read(surface: CatalogSurface) -> None:
    DATA_CATALOG_READS_COUNTER.labels(surface=surface).inc()


def record_catalog_read_failure(surface: CatalogSurface) -> None:
    DATA_CATALOG_READ_FAILURES_COUNTER.labels(surface=surface).inc()
