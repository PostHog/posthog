from collections.abc import Callable, Mapping

from ..message_normalizer.normalizer import RecipeNormalizer
from ..message_normalizer.run_limits import time_limit
from .previews import PREVIEWS_TIME_LIMIT_SECONDS, PreviewSource, TracePreviewSources, out_of_time
from .step_content import built_once, read_step
from .turn import TIMED_OUT, Side, StepSide, TurnSides, TurnStep


def page_turn_sides(
    sources: Mapping[str, TracePreviewSources], *, build_normalizer: Callable[[], RecipeNormalizer], team_id: int
) -> dict[str, TurnSides]:
    """Each trace's turn sides, keyed by trace id. Once `PREVIEWS_TIME_LIMIT_SECONDS` is spent for the whole page, a
    side that failed and every trace not yet read time out. The team's normalizer is built at most once, and only when
    a side needs it."""
    normalizer = built_once(build_normalizer)
    with time_limit(PREVIEWS_TIME_LIMIT_SECONDS):
        return {
            trace_id: _timed_out() if out_of_time() else _turn_sides(trace_id, trace_sources, normalizer, team_id)
            for trace_id, trace_sources in sources.items()
        }


def _timed_out() -> TurnSides:
    side: StepSide = Side(value=None, unread=TIMED_OUT)
    return TurnSides(input=side, output=side)


def _turn_sides(
    trace_id: str, sources: TracePreviewSources, normalizer: Callable[[], RecipeNormalizer], team_id: int
) -> TurnSides:
    def read(source: PreviewSource | None) -> TurnStep | None:
        if source is None:
            return None
        if not source.event_id:
            return TurnStep(
                input=Side(value=None, unread=source.input.unread), output=Side(value=None, unread=source.output.unread)
            )
        # The trace view names the root node by the trace id, and leaves the `$ai_trace` event out of its tree.
        node_id = trace_id if source.kind == "trace" else source.event_id
        reading = read_step(
            source.kind,
            node_id,
            source.input.value,
            source.output.value,
            build_normalizer=normalizer,
            team_id=team_id,
        )
        return TurnStep.of(
            reading, input_unread=source.input.unread, output_unread=source.output.unread, out_of_time=out_of_time()
        )

    first_generation = read(sources.first_generation)
    latest_generation = (
        first_generation if sources.latest_generation == sources.first_generation else read(sources.latest_generation)
    )
    return TurnSides.of(
        state=read(sources.state),
        first_generation=first_generation,
        latest_generation_input=latest_generation.input if latest_generation else None,
        latest_generation=latest_generation,
    )
