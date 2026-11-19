from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Final, Self

from posthog.dataclasses import frozen

from ...facade.contracts import TraceNodeKind
from ..message_normalizer.errors import RecipeTimeoutError
from ..message_normalizer.normalizer import RecipeNormalizer
from ..message_normalizer.run_limits import check_time_limit, time_limit
from ..message_normalizer.values import Value, is_list
from .event import kind_of_event
from .node import IO_KEY_CANDIDATES
from .step_content import built_once, read_step
from .thread import pick_first_generation, pick_user_visible_generation
from .turn import TIMED_OUT, TOO_LARGE, Side, Turn, TurnStep, readable_tail

if TYPE_CHECKING:
    from .preview_queries import PreviewEventRow, PreviewEventValues, StoredValue

PREVIEWS_TIME_LIMIT_SECONDS: Final = 3.0


@frozen
class PreviewSource:
    event_id: str
    kind: TraceNodeKind
    input: Side[Value]
    output: Side[Value]


@frozen
class TracePreviewSources:
    state: PreviewSource | None
    first_generation: PreviewSource | None
    latest_generation: PreviewSource | None


@frozen
class _PreviewEvent:
    row: "PreviewEventRow"

    @property
    def kind(self) -> TraceNodeKind:
        return kind_of_event(self.row.event)


@frozen
class PreviewPicks:
    state: str | None
    first_generation: str | None
    latest_generation: str | None

    @classmethod
    def of(cls, events: Sequence[_PreviewEvent]) -> Self:
        first = pick_first_generation(events)
        latest = pick_user_visible_generation(events)
        state = max(
            (event for event in events if event.kind == "trace" and event.row.has_state),
            key=lambda event: event.row.timestamp,
            default=None,
        )
        return cls(
            state=state.row.uuid if state else None,
            first_generation=first.row.uuid if first else None,
            latest_generation=latest.row.uuid if latest else None,
        )


@frozen
class PreviewReads:
    trace_ids: tuple[str, ...]
    input_ids: tuple[str, ...]
    output_ids: tuple[str, ...]
    state_ids: tuple[str, ...]

    @classmethod
    def of(cls, picks: Mapping[str, PreviewPicks], *, latest_input: bool = False) -> Self:
        def ids(*roles: str | None) -> tuple[str, ...]:
            return tuple(sorted({event_id for event_id in roles if event_id is not None}))

        states = [picked.state for picked in picks.values()]
        return cls(
            trace_ids=tuple(picks),
            input_ids=ids(
                *states,
                *(picked.first_generation for picked in picks.values()),
                *(picked.latest_generation for picked in picks.values() if latest_input),
            ),
            output_ids=ids(*states, *(picked.latest_generation for picked in picks.values())),
            state_ids=ids(*states),
        )

    @property
    def event_ids(self) -> tuple[str, ...]:
        return tuple(sorted({*self.input_ids, *self.output_ids}))


def pick_preview_events(rows: Sequence["PreviewEventRow"]) -> dict[str, PreviewPicks]:
    """Each trace's state event, first generation and latest generation, keyed by trace id. A trace that has none of
    them has no entry."""
    grouped: dict[str, dict[str, _PreviewEvent]] = {}
    # Rows in time order, so each pick resolves a tie in time the way the trace view does.
    for row in sorted(rows, key=lambda row: (row.timestamp, row.uuid)):
        grouped.setdefault(row.trace_id, {})[row.uuid] = _PreviewEvent(row=row)
    picks = {trace_id: PreviewPicks.of(list(events.values())) for trace_id, events in grouped.items()}
    return {
        trace_id: picked
        for trace_id, picked in picks.items()
        if picked.state or picked.first_generation or picked.latest_generation
    }


def side_of_values(values: Mapping[str, "StoredValue"], keys: Sequence[str]) -> Side[Value]:
    # The step read shows the first key present, so an over-cap value still stands for its side and is not read.
    key = next((key for key in keys if key in values and values[key].present), None)
    if key is None:
        return Side(value=None, unread=None)
    stored = values[key]
    if stored.item_over_caps is not None and is_list(stored.value):
        return readable_tail(stored.value, stored.item_over_caps)
    if stored.over_cap:
        return Side(value=None, unread=TOO_LARGE)
    return Side(value=stored.value, unread=None)


def _source(event: "PreviewEventValues | None") -> PreviewSource | None:
    if event is None:
        return None
    kind = kind_of_event(event.event)
    candidates = IO_KEY_CANDIDATES[kind]
    return PreviewSource(
        event_id=event.uuid,
        kind=kind,
        input=side_of_values(event.values, candidates.input),
        output=side_of_values(event.values, candidates.output),
    )


def preview_sources(
    picks: Mapping[str, PreviewPicks], values: Mapping[str, "PreviewEventValues"]
) -> dict[str, TracePreviewSources]:
    def source(event_id: str | None) -> PreviewSource | None:
        return _source(values.get(event_id)) if event_id is not None else None

    return {
        trace_id: TracePreviewSources(
            state=source(picked.state),
            first_generation=source(picked.first_generation),
            latest_generation=source(picked.latest_generation),
        )
        for trace_id, picked in picks.items()
    }


def timed_out_sources(
    picks: Mapping[str, PreviewPicks], rows: Sequence["PreviewEventRow"]
) -> dict[str, TracePreviewSources]:
    """The sources of a page whose values were not read in time: every picked side timed out."""
    events = {row.uuid: row.event for row in rows}
    timed_out = Side(value=None, unread=TIMED_OUT)

    def source(event_id: str | None) -> PreviewSource | None:
        if event_id is None:
            return None
        return PreviewSource(event_id=event_id, kind=kind_of_event(events[event_id]), input=timed_out, output=timed_out)

    return {
        trace_id: TracePreviewSources(
            state=source(picked.state),
            first_generation=source(picked.first_generation),
            latest_generation=source(picked.latest_generation),
        )
        for trace_id, picked in picks.items()
    }


def page_turns(
    sources: Mapping[str, TracePreviewSources], *, build_normalizer: Callable[[], RecipeNormalizer], team_id: int
) -> dict[str, Turn]:
    """Each trace's turn, keyed by trace id. Once `PREVIEWS_TIME_LIMIT_SECONDS` is spent for the whole page, a side
    that failed and every trace not yet read time out. The team's normalizer is built at most once, and only when a
    side needs it."""
    normalizer = built_once(build_normalizer)
    with time_limit(PREVIEWS_TIME_LIMIT_SECONDS):
        return {
            trace_id: Turn(message=TIMED_OUT, answer=TIMED_OUT)
            if _out_of_time()
            else _turn(trace_sources, normalizer, team_id)
            for trace_id, trace_sources in sources.items()
        }


def _out_of_time() -> bool:
    try:
        check_time_limit()
    except RecipeTimeoutError:
        return True
    return False


def _turn(sources: TracePreviewSources, normalizer: Callable[[], RecipeNormalizer], team_id: int) -> Turn:
    def read(source: PreviewSource | None) -> TurnStep | None:
        if source is None:
            return None
        reading = read_step(
            source.kind,
            source.event_id,
            source.input.value,
            source.output.value,
            build_normalizer=normalizer,
            team_id=team_id,
        )
        return TurnStep.of(
            reading,
            input_unread=source.input.unread,
            output_unread=source.output.unread,
            out_of_time=_out_of_time(),
        )

    first_generation = read(sources.first_generation)
    return Turn.of(
        state=read(sources.state),
        first_generation=first_generation,
        latest_generation=first_generation
        if sources.latest_generation == sources.first_generation
        else read(sources.latest_generation),
    )
