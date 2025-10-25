from typing import Optional, Union

from django.db import models
from django.utils import timezone

from posthog.models.utils import RootTeamMixin, UUIDModel


class CohortCalculationHistory(RootTeamMixin, UUIDModel):
    """
    Track cohort calculation statistics for performance monitoring and debugging.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    cohort = models.ForeignKey("posthog.Cohort", on_delete=models.CASCADE)

    # Calculation metadata
    filters = models.JSONField(help_text="Cohort filters/properties at time of calculation")
    count = models.PositiveIntegerField(null=True, blank=True, help_text="Number of people in cohort")

    # Timing
    started_at = models.DateTimeField(default=timezone.now, help_text="When calculation started")
    finished_at = models.DateTimeField(null=True, blank=True, help_text="When calculation finished")

    # ClickHouse query information (stored as array for future chunking support)
    queries = models.JSONField(
        blank=True,
        default=None,
        null=True,
        help_text="Array of query information (query, query_id, query_ms, memory_mb, read_rows, written_rows)",
    )

    # Error handling
    error = models.TextField(null=True, blank=True, help_text="Error message if calculation failed")

    class Meta:
        db_table = "posthog_cohortcalculationhistory"
        indexes = [
            models.Index(fields=["team", "cohort"]),
            models.Index(fields=["team", "started_at"]),
        ]

    def __str__(self):
        return f"CohortCalculationHistory(cohort={self.cohort_id}, started_at={self.started_at})"

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate duration in seconds if both start and end times are available"""
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    @property
    def is_completed(self) -> bool:
        """Check if calculation is completed (successfully or with error)"""
        return self.finished_at is not None

    @property
    def is_successful(self) -> bool:
        """Check if calculation completed successfully"""
        return self.finished_at is not None and self.error is None

    def add_query_info(
        self,
        query: Optional[str] = None,
        query_id: Optional[str] = None,
        query_ms: Optional[int] = None,
        memory_mb: Optional[int] = None,
        read_rows: Optional[int] = None,
        written_rows: Optional[int] = None,
    ) -> None:
        """Add query information to the queries array"""
        query_info: dict[str, Union[str, int]] = {}
        if query is not None:
            query_info["query"] = query
        if query_id is not None:
            query_info["query_id"] = query_id
        if query_ms is not None:
            query_info["query_ms"] = query_ms
        if memory_mb is not None:
            query_info["memory_mb"] = memory_mb
        if read_rows is not None:
            query_info["read_rows"] = read_rows
        if written_rows is not None:
            query_info["written_rows"] = written_rows

        if query_info:
            # Ensure queries is always a list
            if self.queries is None:
                self.queries = []
            self.queries.append(query_info)

    @property
    def total_query_ms(self) -> Optional[int]:
        """Get total query duration across all queries"""
        if not self.queries:
            return None
        return sum(q.get("query_ms", 0) for q in self.queries if q.get("query_ms"))

    @property
    def total_memory_mb(self) -> Optional[int]:
        """Get total memory usage across all queries"""
        if not self.queries:
            return None
        return sum(q.get("memory_mb", 0) for q in self.queries if q.get("memory_mb"))

    @property
    def total_read_rows(self) -> Optional[int]:
        """Get total rows read across all queries"""
        if not self.queries:
            return None
        return sum(q.get("read_rows", 0) for q in self.queries if q.get("read_rows"))

    @property
    def total_written_rows(self) -> Optional[int]:
        """Get total rows written across all queries"""
        if not self.queries:
            return None
        return sum(q.get("written_rows", 0) for q in self.queries if q.get("written_rows"))

    @property
    def main_query(self) -> Optional[str]:
        """Get the main query (first query in the array)"""
        if self.queries:
            return self.queries[0].get("query")
        return None
