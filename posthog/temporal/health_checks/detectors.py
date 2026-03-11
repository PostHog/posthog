from dataclasses import dataclass


@dataclass(frozen=True)
class HealthExecutionPolicy:
    batch_size: int
    max_concurrent: int

    def __post_init__(self) -> None:
        if self.batch_size <= 0:
            raise ValueError(f"batch_size must be > 0, got {self.batch_size}")
        if self.max_concurrent <= 0:
            raise ValueError(f"max_concurrent must be > 0, got {self.max_concurrent}")


DEFAULT_EXECUTION_POLICY = HealthExecutionPolicy(batch_size=1000, max_concurrent=5)
CLICKHOUSE_BATCH_EXECUTION_POLICY = HealthExecutionPolicy(batch_size=250, max_concurrent=1)
