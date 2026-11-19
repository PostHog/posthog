from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Final

from posthog.dataclasses import frozen
from posthog.exceptions import ClickHouseEstimatedQueryExecutionTimeTooLong, ClickHouseQueryTimeOut
from posthog.models import Team, User

from ...facade.contracts import TraceNodeKind
from ..message_normalizer.values import Value
from .events_fallback import FallbackWindow, page_window
from .preview_queries import PreviewEventRow, load_preview_event_rows, load_preview_values
from .previews import (
    PreviewPicks,
    PreviewReads,
    PreviewSource,
    TracePreviewSources,
    pick_preview_events,
    preview_sources,
    timed_out_sources,
)
from .turn import TIMED_OUT, Side

TURN_PICKS_QUERY_NAME = "ai_trace_turn_picks"
TURNS_QUERY_NAME = "ai_trace_turns"
# Items of the latest generation's input read from its end. Each item is read up to `PREVIEW_SOURCE_MAX_BYTES`.
TURN_INPUT_ITEMS: Final = 200
# Bytes of one side's input tail a turn keeps, the newest items first. An older item that does not fit is left unread.
TURN_SIDE_MAX_BYTES: Final = 524_288

_DATABASE_TIMEOUTS = (ClickHouseQueryTimeOut, ClickHouseEstimatedQueryExecutionTimeTooLong)


@frozen
class TurnSources:
    state: PreviewSource | None
    first_generation: PreviewSource | None
    latest_generation: PreviewSource | None
    latest_generation_input: Side[Value] | None


def _turn_sources(sources: TracePreviewSources) -> TurnSources:
    latest = sources.latest_generation
    return TurnSources(
        state=sources.state,
        first_generation=sources.first_generation,
        latest_generation=latest,
        latest_generation_input=latest.input if latest else None,
    )


def _timed_out_traces(trace_ids: Sequence[str]) -> dict[str, TurnSources]:
    """Traces whose picks were not read in time, so no event is known to read from. Their sources have no event id."""
    timed_out = Side(value=None, unread=TIMED_OUT)

    def source(kind: TraceNodeKind) -> PreviewSource:
        return PreviewSource(event_id="", kind=kind, input=timed_out, output=timed_out)

    return {
        trace_id: TurnSources(
            state=source("trace"),
            first_generation=source("generation"),
            latest_generation=source("generation"),
            latest_generation_input=timed_out,
        )
        for trace_id in trace_ids
    }


def _read_sources(
    team: Team,
    user: User | None,
    rows: Sequence[PreviewEventRow],
    picks: Mapping[str, PreviewPicks],
    window: FallbackWindow | None,
) -> dict[str, TurnSources]:
    try:
        values = load_preview_values(
            team,
            user,
            PreviewReads.of(picks, latest_input=True),
            window=window,
            name=TURNS_QUERY_NAME,
            tail=TURN_INPUT_ITEMS,
            tail_max_bytes=TURN_SIDE_MAX_BYTES,
        )
    except _DATABASE_TIMEOUTS:
        sources = timed_out_sources(picks, rows)
    else:
        sources = preview_sources(picks, values)
    return {trace_id: _turn_sources(trace_sources) for trace_id, trace_sources in sources.items()}


def _read_rows(
    team: Team, user: User | None, trace_ids: Sequence[str], window: FallbackWindow | None
) -> list[PreviewEventRow]:
    return load_preview_event_rows(team, user, trace_ids, window=window, name=TURN_PICKS_QUERY_NAME)


def load_turn_sources(
    team: Team, user: User | None, trace_ids: Sequence[str], *, earliest: datetime, latest: datetime
) -> dict[str, TurnSources]:
    """The values each trace's turn is built from, keyed by trace id: the state, the first generation's input, and the
    latest generation's input and output. A trace with no state event and no generation has no entry.

    Reads `posthog.ai_events`, and the traces it misses from the shared events table between `earliest` and `latest`,
    the first timestamps of the traces, widened by the fallback hints."""
    requested = list(dict.fromkeys(trace_ids))
    if not requested:
        return {}
    try:
        ai_events_rows = _read_rows(team, user, requested, None)
    except _DATABASE_TIMEOUTS:
        return _timed_out_traces(requested)
    found = {row.trace_id for row in ai_events_rows}
    missing = [trace_id for trace_id in requested if trace_id not in found]
    sources = _read_sources(team, user, ai_events_rows, pick_preview_events(ai_events_rows), None)
    if missing:
        window = page_window([earliest, latest])
        try:
            events_rows = _read_rows(team, user, missing, window)
        except _DATABASE_TIMEOUTS:
            return sources | _timed_out_traces(missing)
        sources |= _read_sources(team, user, events_rows, pick_preview_events(events_rows), window)
    return sources
