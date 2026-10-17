"""Data catalog's sources for the "For you today" list. Today finds this module by name."""

from products.today.backend.facade.contracts import HighlightSource

from ..today_highlights import find_pending_approvals

HIGHLIGHT_SOURCES = (
    HighlightSource(
        name="data_catalog_approvals",
        find=find_pending_approvals,
        scopes=("data_catalog:read", "data_catalog_approval:write"),
    ),
)
