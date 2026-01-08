import dataclasses


@dataclasses.dataclass
class BatchReadySignal:
    """Signal sent from ET to L workflow after each batch is written to temp S3."""

    batch_path: str
    batch_number: int
    schema_path: str
    row_count: int
    primary_keys: list[str] | None
    sync_type: str


@dataclasses.dataclass
class ETCompleteSignal:
    """Signal sent from ET to L workflow when extraction is complete."""

    manifest_path: str
    total_batches: int
    total_rows: int
