from products.today.backend.facade.contracts import HighlightSource

from ..today_highlights import find_evaluation_number, name_evaluation_numbers

HIGHLIGHT_SOURCES = (
    HighlightSource(
        name="evaluation_numbers",
        find=find_evaluation_number,
        scopes=("evaluation:read",),
        pulse_order=-1,
        number_names=name_evaluation_numbers,
    ),
)
