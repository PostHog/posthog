from collections.abc import Callable, Mapping

from ..message_normalizer.normalizer import RecipeNormalizer
from .previews import TracePreviewSources, TraceSteps, page_of_turns
from .turn import TIMED_OUT, Side, StepSide, TurnSides

_TIMED_OUT_SIDE: StepSide = Side(value=None, unread=TIMED_OUT)


def page_turn_sides(
    sources: Mapping[str, TracePreviewSources], *, build_normalizer: Callable[[], RecipeNormalizer], team_id: int
) -> dict[str, TurnSides]:
    """Each trace's turn sides, keyed by trace id, read as `page_of_turns` reads a page."""
    return page_of_turns(
        sources,
        _turn_sides,
        TurnSides(input=_TIMED_OUT_SIDE, output=_TIMED_OUT_SIDE),
        build_normalizer=build_normalizer,
        team_id=team_id,
    )


def _turn_sides(steps: TraceSteps) -> TurnSides:
    return TurnSides.of(
        state=steps.state,
        first_generation=steps.first_generation,
        latest_generation_input=steps.latest_generation.input if steps.latest_generation else None,
        latest_generation=steps.latest_generation,
    )
