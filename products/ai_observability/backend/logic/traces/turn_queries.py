from collections.abc import Sequence
from datetime import datetime
from typing import Final

from posthog.models import Team, User

from ...facade.contracts import TraceNodeKind
from .events_fallback import FallbackWindow, page_window
from .preview_queries import DATABASE_TIMEOUTS, SourceReads, read_sources
from .previews import PreviewSource, TracePreviewSources
from .turn import TIMED_OUT, Side

TURN_PICKS_QUERY_NAME = "ai_trace_turn_picks"
TURNS_QUERY_NAME = "ai_trace_turns"
# Items of the latest generation's input read from its end. Each item is read up to `PREVIEW_SOURCE_MAX_BYTES`.
TURN_INPUT_ITEMS: Final = 200
# Bytes of one side's input tail a turn keeps, the newest items first. An older item that does not fit is left unread.
TURN_SIDE_MAX_BYTES: Final = 524_288

TURN_READS: Final = SourceReads(
    picks_name=TURN_PICKS_QUERY_NAME,
    values_name=TURNS_QUERY_NAME,
    latest_input=True,
    tail=TURN_INPUT_ITEMS,
    tail_max_bytes=TURN_SIDE_MAX_BYTES,
)


def _timed_out_traces(trace_ids: Sequence[str]) -> dict[str, TracePreviewSources]:
    """Traces whose picks were not read in time, so no event is known to read from. Their sources have no event id."""
    timed_out = Side(value=None, unread=TIMED_OUT)

    def source(kind: TraceNodeKind) -> PreviewSource:
        return PreviewSource(event_id="", kind=kind, input=timed_out, output=timed_out)

    return {
        trace_id: TracePreviewSources(
            state=source("trace"), first_generation=source("generation"), latest_generation=source("generation")
        )
        for trace_id in trace_ids
    }


def _read(
    team: Team, user: User | None, trace_ids: Sequence[str], window: FallbackWindow | None
) -> dict[str, TracePreviewSources]:
    try:
        return read_sources(team, user, trace_ids, TURN_READS, window=window)
    except DATABASE_TIMEOUTS:
        return _timed_out_traces(trace_ids)


def load_turn_sources(
    team: Team, user: User | None, trace_ids: Sequence[str], *, earliest: datetime, latest: datetime
) -> dict[str, TracePreviewSources]:
    """The values each trace's turn is built from, keyed by trace id: the state, the first generation's input, and the
    latest generation's input and output. A trace with no state event and no generation has no entry.

    Reads `posthog.ai_events`, and the traces it misses from the shared events table between `earliest` and `latest`,
    the first timestamps of the traces, widened by the fallback hints."""
    requested = list(dict.fromkeys(trace_ids))
    sources = _read(team, user, requested, None)
    missing = [trace_id for trace_id in requested if trace_id not in sources]
    if missing:
        sources |= _read(team, user, missing, page_window([earliest, latest]))
    return sources
