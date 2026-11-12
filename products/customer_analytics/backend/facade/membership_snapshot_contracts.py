from dataclasses import field
from datetime import datetime
from typing import Literal
from uuid import UUID

from posthog.dataclasses import frozen

from products.data_modeling.backend.facade.contracts import MaterializedQuerySnapshot

MAX_CHECKPOINT_KEY_BYTES = 16_384


@frozen
class MembershipSnapshotInput:
    team_id: int
    group_type_index: int
    source_view_id: str
    source_job_id: str
    checked_at: datetime
    expected_rows: int
    max_rows: int
    membership_version: int = 0
    dry_run: bool = True
    batch_size: int = 5_000

    def __post_init__(self) -> None:
        UUID(self.source_view_id)
        UUID(self.source_job_id)
        if self.team_id <= 0 or not 0 <= self.group_type_index <= 4:
            raise ValueError("Supply a valid project and account group type")
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("Supply the snapshot check time with a timezone")
        if not 0 < self.max_rows <= self.expected_rows or not 0 < self.batch_size <= 5_000:
            raise ValueError("Supply a positive row limit and a batch size of at most 5000")
        if self.membership_version < 0 or (not self.dry_run and self.membership_version == 0):
            raise ValueError("Supply the existing membership configuration version before writing")


@frozen
class MembershipSnapshotCheckpoint:
    rows_read: int = 0
    rows_written: int = 0
    batches: int = 0
    group_key: str = field(default="", repr=False)
    distinct_id: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not 0 <= self.rows_written <= self.rows_read or self.batches < 0:
            raise ValueError("Invalid membership snapshot checkpoint")
        if bool(self.group_key) != bool(self.distinct_id) or bool(self.rows_read) != bool(self.group_key):
            raise ValueError("The checkpoint must include both membership keys after the first batch")
        if len(self.group_key.encode()) + len(self.distinct_id.encode()) > MAX_CHECKPOINT_KEY_BYTES:
            raise ValueError("Membership keys exceed the checkpoint byte limit")


@frozen
class MembershipSnapshotBatch:
    input: MembershipSnapshotInput
    snapshot: MaterializedQuerySnapshot
    checkpoint: MembershipSnapshotCheckpoint = field(default_factory=MembershipSnapshotCheckpoint)


@frozen
class MembershipSnapshotStep:
    checkpoint: MembershipSnapshotCheckpoint
    completed: bool


@frozen
class MembershipSnapshotStatus:
    row_limit: int = 0
    expected_rows: int = 0
    dry_run: bool = True
    status: Literal["starting", "running", "failed", "completed", "cancelled"] = "starting"
    rows_read: int = 0
    rows_written: int = 0
    batches: int = 0
    error_type: str = ""
