"""Choice enums of the data modeling contracts. No Django imports, and light enough for the models to import."""

from posthog.enums import LabeledStrEnum


class DataModelingJobStatus(LabeledStrEnum):
    CANCELLED = "Cancelled", "Cancelled"
    COMPLETED = "Completed", "Completed"
    FAILED = "Failed", "Failed"
    RUNNING = "Running", "Running"
    SKIPPED = "Skipped", "Skipped"


class DataModelingJobEngine(LabeledStrEnum):
    CLICKHOUSE = "clickhouse", "ClickHouse"
    LEGACY_DUCKGRES = "duckgres", "Duckgres"
    MANAGED_WAREHOUSE = "managed_warehouse", "Managed warehouse"


class DataModelingJobRunMode(LabeledStrEnum):
    FULL_REFRESH = "full_refresh", "Full refresh"
    INCREMENTAL = "incremental", "Incremental"


class NodeType(LabeledStrEnum):
    TABLE = "table"
    VIEW = "view"
    MAT_VIEW = "matview"
    ENDPOINT = "endpoint"
    METRIC = "metric"


class LineageIssueKind(LabeledStrEnum):
    SYNC_FAILED = "sync_failed"
    UNRESOLVED = "unresolved"


class ViewEngineTarget(LabeledStrEnum):
    CLICKHOUSE = "clickhouse", "ClickHouse"
    MANAGED_TRINO = "managed_trino", "Hosted Trino"
    CONNECTION = "connection", "Direct connection"


class ViewEngineDialect(LabeledStrEnum):
    HOGQL = "hogql", "HogQL"
    RAW = "raw", "Raw SQL"


class ViewColumnSource(LabeledStrEnum):
    CLICKHOUSE_PROBE = "clickhouse_probe", "ClickHouse probe"
    CLIENT_TYPES = "client_types", "Column types sent by the client"
