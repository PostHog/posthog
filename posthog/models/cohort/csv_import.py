import os
import csv
import tempfile
from dataclasses import dataclass, field
from datetime import timedelta
from typing import IO, Any, Optional

from django.db import models
from django.utils import timezone

from posthog.models.utils import RootTeamMixin, UUIDModel

# Unmatched IDs (which can be the entire CSV when nothing resolved) are written
# to object storage rather than embedded in the row, both to avoid bloating the
# DB and so we can hand the user a downloadable artifact. The file is short-
# lived: we only keep it around long enough for the user to triage their import.
UNMATCHED_RECORDS_TTL = timedelta(hours=24)

# Header for the unmatched-records CSV. Single column so the file can be
# round-tripped back into another import attempt.
UNMATCHED_RECORDS_CSV_HEADER = ["id"]


class CohortCSVImport(RootTeamMixin, UUIDModel):
    """
    Track CSV import attempts for static cohorts.

    Populated in two stages:
      1. Synchronously in the API request after parsing the CSV (rows_total,
         rows_skipped, ids_submitted, id_type, email_property_key, filename).
      2. Asynchronously by `calculate_cohort_from_list` after person matching
         and insertion completes (persons_matched, persons_added,
         persons_already_in_cohort, unmatched_count, unmatched_records_location,
         unmatched_records_expires_at, finished_at, error).
    """

    ID_TYPE_DISTINCT_ID = "distinct_id"
    ID_TYPE_PERSON_ID = "person_id"
    ID_TYPE_EMAIL = "email"
    ID_TYPE_CHOICES = [
        (ID_TYPE_DISTINCT_ID, "Distinct ID"),
        (ID_TYPE_PERSON_ID, "Person ID"),
        (ID_TYPE_EMAIL, "Email"),
    ]

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    cohort = models.ForeignKey("posthog.Cohort", on_delete=models.CASCADE, related_name="csv_imports")
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)

    # Lifecycle
    started_at = models.DateTimeField(default=timezone.now, help_text="When the upload was received")
    finished_at = models.DateTimeField(null=True, blank=True, help_text="When async matching/insertion completed")

    # Source metadata
    filename = models.CharField(max_length=512, null=True, blank=True, help_text="Uploaded filename, if available")
    id_type = models.CharField(max_length=32, choices=ID_TYPE_CHOICES, help_text="How rows were interpreted")
    email_property_key = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Person property key matched against, when id_type='email'",
    )

    # Parse stage (sync)
    rows_total = models.PositiveIntegerField(null=True, blank=True, help_text="Total data rows read from the CSV")
    rows_skipped = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Rows skipped due to malformed structure (wrong column count, empty cells)",
    )
    ids_submitted = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of non-empty IDs handed off to the matcher",
    )

    # Match/insert stage (async)
    persons_matched = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Unique persons resolved from the submitted IDs",
    )
    persons_added = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Persons newly inserted into the cohort",
    )
    persons_already_in_cohort = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Matched persons that were already cohort members",
    )
    unmatched_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Submitted IDs that did not resolve to a person",
    )
    unmatched_records_location = models.TextField(
        null=True,
        blank=True,
        help_text="Object-storage path of the CSV listing every input ID that did not resolve to a person.",
    )
    unmatched_records_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "When the unmatched-records file is no longer guaranteed to be downloadable "
            f"(default {int(UNMATCHED_RECORDS_TTL.total_seconds() // 3600)}h after upload)."
        ),
    )

    # Errors
    error = models.TextField(null=True, blank=True, help_text="Error message if the import failed")
    error_code = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="Error code for categorizing failures (e.g., 'parse_error', 'no_valid_ids')",
    )

    class Meta:
        db_table = "posthog_cohortcsvimport"
        indexes = [
            models.Index(fields=["team", "cohort", "-started_at"]),
            models.Index(fields=["cohort", "-started_at"]),
        ]

    def __str__(self) -> str:
        return f"CohortCSVImport(cohort={self.cohort_id}, started_at={self.started_at})"

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    @property
    def is_completed(self) -> bool:
        return self.finished_at is not None

    @property
    def is_successful(self) -> bool:
        return self.is_completed and self.error is None

    @property
    def has_unmatched_records_file(self) -> bool:
        """True when an unmatched-records artifact exists and hasn't expired."""
        if not self.unmatched_records_location:
            return False
        if self.unmatched_records_expires_at is None:
            return True
        return self.unmatched_records_expires_at > timezone.now()


@dataclass
class CSVImportTracker:
    """
    Accumulates per-stage metrics across batches during async matching/insertion.

    Unmatched IDs can run into the millions, so we stream them straight to a
    temporary file instead of buffering in memory. The Celery task uploads
    that file to object storage once the import finishes; the tracker itself
    is responsible only for opening, writing, and cleaning up the temp file.

    Lifecycle:
      tracker = CSVImportTracker()
      try:
          ... record_matched / record_unmatched / record_added / record_already_in_cohort ...
          tracker.apply_to(import_record)             # copy counts onto the row
          path = tracker.unmatched_records_temp_path  # None when nothing was unmatched
          if path:
              ... upload `path` to object storage, set location + expires_at ...
      finally:
          tracker.cleanup()                            # always delete the temp file
    """

    persons_matched: int = 0
    persons_added: int = 0
    persons_already_in_cohort: int = 0
    unmatched_count: int = 0

    _matched_person_uuids: set[str] = field(default_factory=set)
    _unmatched_file: Optional[IO[str]] = field(default=None, init=False, repr=False)
    _unmatched_writer: Any = field(default=None, init=False, repr=False)
    _unmatched_path: Optional[str] = field(default=None, init=False, repr=False)
    _cleaned_up: bool = field(default=False, init=False, repr=False)

    def record_matched(self, matched_person_uuids: list[str]) -> None:
        for uuid in matched_person_uuids:
            uuid_str = str(uuid)
            if uuid_str not in self._matched_person_uuids:
                self._matched_person_uuids.add(uuid_str)
                self.persons_matched += 1

    def record_unmatched(self, ids: list[str]) -> None:
        if not ids:
            return
        self._ensure_unmatched_file()
        assert self._unmatched_writer is not None
        for raw in ids:
            self._unmatched_writer.writerow([str(raw)])
        self.unmatched_count += len(ids)

    def record_added(self, count: int) -> None:
        self.persons_added += count

    def record_already_in_cohort(self, count: int) -> None:
        self.persons_already_in_cohort += count

    @property
    def unmatched_records_temp_path(self) -> Optional[str]:
        """Path to the flushed CSV of unmatched IDs, or None if nothing was unmatched."""
        if self._unmatched_file is None:
            return None
        self._unmatched_file.flush()
        return self._unmatched_path

    def apply_to(self, import_record: CohortCSVImport) -> None:
        """Copy aggregate counts onto the import row. Caller handles file location."""
        import_record.persons_matched = self.persons_matched
        import_record.persons_added = self.persons_added
        import_record.persons_already_in_cohort = self.persons_already_in_cohort
        import_record.unmatched_count = self.unmatched_count
        # Note: unmatched_sample is not populated by the streaming tracker
        # as unmatched IDs are written directly to a temp file

    def cleanup(self) -> None:
        """Close and delete the temp file. Idempotent."""
        if self._cleaned_up:
            return
        self._cleaned_up = True
        if self._unmatched_file is not None:
            try:
                self._unmatched_file.close()
            except Exception:  # noqa: BLE001
                pass
        if self._unmatched_path is not None:
            try:
                os.unlink(self._unmatched_path)
            except FileNotFoundError:
                pass
            except OSError:
                # Best effort — operator can sweep stale temp files.
                pass

    def _ensure_unmatched_file(self) -> None:
        if self._unmatched_file is not None:
            return
        # delete=False so we can close the handle, hand the path to the uploader,
        # and reopen the file from a clean offset on the upload side.
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".csv",
            prefix="cohort-csv-import-unmatched-",
            delete=False,
        )
        writer = csv.writer(handle)
        writer.writerow(UNMATCHED_RECORDS_CSV_HEADER)
        self._unmatched_file = handle
        self._unmatched_writer = writer
        self._unmatched_path = handle.name
