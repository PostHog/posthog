"""Customer analytics' sources for the "For you today" list. Today finds this module by name."""

from products.today.backend.facade.contracts import HighlightSource

from ..today_highlights import find_key_metrics

HIGHLIGHT_SOURCES = (
    HighlightSource(name="key_metrics", find=find_key_metrics, scopes=("customer_analytics:read",), pulse_order=2),
)
