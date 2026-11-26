from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from posthog.hogql import ast

from posthog.dataclasses import frozen

FALLBACK_BEFORE_HINT = timedelta(minutes=10)
FALLBACK_AFTER_HINT = timedelta(days=7)
# The legacy trace view used this date as its default range start when a link carried no timestamp.
UNHINTED_FALLBACK_START = datetime(2025, 1, 10, tzinfo=UTC)
# The default of `ai_events.retention_days` in posthog/models/ai_events/sql.py. No ingestion path writes another value.
AI_EVENTS_RETENTION_DAYS = 30


@frozen
class FallbackWindow:
    start: datetime
    end: datetime

    def may_hold_aged_out_events(self, now: datetime) -> bool:
        """Whether `posthog.ai_events` may already have dropped events of this window, so a read that finds nothing
        there cannot tell an event that never existed from one that aged out."""
        # A row leaves ai_events at the start of the day `retention_days` after its date, so up to a day before the full
        # retention has passed.
        return self.start < now - timedelta(days=AI_EVENTS_RETENTION_DAYS - 1)


def fallback_window(timestamp_hint: datetime) -> FallbackWindow:
    """Raises OverflowError when the window around the hint leaves the datetime range."""
    return FallbackWindow(start=timestamp_hint - FALLBACK_BEFORE_HINT, end=timestamp_hint + FALLBACK_AFTER_HINT)


def page_window(first_timestamps: Sequence[datetime]) -> FallbackWindow:
    return FallbackWindow(
        start=min(first_timestamps) - FALLBACK_BEFORE_HINT, end=max(first_timestamps) + FALLBACK_AFTER_HINT
    )


def unhinted_window() -> FallbackWindow:
    return FallbackWindow(
        start=UNHINTED_FALLBACK_START - FALLBACK_BEFORE_HINT, end=datetime.now(UTC) + FALLBACK_AFTER_HINT
    )


def events_filter(*, trace_filter: ast.Expr, event_filter: ast.Expr, window: FallbackWindow | None) -> ast.Expr:
    if window is None:
        # The shared events table is not sorted by trace id, so a read without a window must not scan it.
        return ast.Constant(value=False)
    # The events table sorts by event and has no index on uuid, so without the event filter the root's uuid lookup
    # scans every event of the team in the window.
    return ast.And(
        exprs=[
            event_filter,
            trace_filter,
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=window.start),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=window.end),
            ),
        ]
    )
