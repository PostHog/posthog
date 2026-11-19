from collections.abc import Callable, Mapping

from ..message_normalizer.normalizer import RecipeNormalizer
from ..message_normalizer.run_limits import time_limit
from ..message_normalizer.values import MISSING
from .previews import PREVIEWS_TIME_LIMIT_SECONDS, PreviewSource, out_of_time
from .step_content import built_once, read_step
from .turn import TIMED_OUT, Side, StepSide, TurnSides, TurnStep
from .turn_queries import TurnSources


def page_turn_sides(
    sources: Mapping[str, TurnSources], *, build_normalizer: Callable[[], RecipeNormalizer], team_id: int
) -> dict[str, TurnSides]:
    """Each trace's turn sides, keyed by trace id. Once `PREVIEWS_TIME_LIMIT_SECONDS` is spent for the whole page, a
    side that failed and every trace not yet read time out. The team's normalizer is built at most once, and only when
    a side needs it."""
    normalizer = built_once(build_normalizer)
    with time_limit(PREVIEWS_TIME_LIMIT_SECONDS):
        return {
            trace_id: _timed_out() if out_of_time() else _turn_sides(trace_sources, normalizer, team_id)
            for trace_id, trace_sources in sources.items()
        }


def _timed_out() -> TurnSides:
    side: StepSide = Side(value=None, unread=TIMED_OUT)
    return TurnSides(input=side, output=side)


def _turn_sides(sources: TurnSources, normalizer: Callable[[], RecipeNormalizer], team_id: int) -> TurnSides:
    def read(source: PreviewSource | None) -> TurnStep | None:
        if source is None:
            return None
        if not source.event_id:
            return TurnStep(
                input=Side(value=None, unread=source.input.unread), output=Side(value=None, unread=source.output.unread)
            )
        reading = read_step(
            source.kind,
            source.event_id,
            source.input.value,
            source.output.value,
            build_normalizer=normalizer,
            team_id=team_id,
        )
        return TurnStep.of(
            reading, input_unread=source.input.unread, output_unread=source.output.unread, out_of_time=out_of_time()
        )

    def read_latest_input() -> StepSide | None:
        latest, latest_input = sources.latest_generation, sources.latest_generation_input
        if latest is None or latest_input is None:
            return None
        if not latest.event_id:
            return Side(value=None, unread=latest_input.unread)
        reading = read_step(
            latest.kind,
            latest.event_id,
            latest_input.value,
            MISSING,
            build_normalizer=normalizer,
            team_id=team_id,
        )
        return TurnStep.of(
            reading, input_unread=latest_input.unread, output_unread=None, out_of_time=out_of_time()
        ).input

    first_generation = read(sources.first_generation)
    return TurnSides.of(
        state=read(sources.state),
        first_generation=first_generation,
        latest_generation_input=read_latest_input(),
        latest_generation=first_generation
        if sources.latest_generation == sources.first_generation
        else read(sources.latest_generation),
    )
