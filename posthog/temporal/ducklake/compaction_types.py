from pydantic import BaseModel


class DucklakeCompactionInput(BaseModel):
    """Input for the DuckLake compaction workflow."""

    # Target file size for compaction (default: 256MB)
    target_file_size: str = "256MB"
    # Tables to compact (if empty, compacts all tables)
    tables: list[str] = []
    # Whether to run in dry-run mode (no actual compaction)
    dry_run: bool = False
