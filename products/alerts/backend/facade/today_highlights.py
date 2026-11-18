"""Alerts' sources for the "For you today" list. Today finds this module by name."""

from products.today.backend.facade.contracts import HighlightSource

from ..today_highlights import find_firing_alerts

HIGHLIGHT_SOURCES = (HighlightSource(name="alerts", find=find_firing_alerts, scopes=("alert:read",)),)
