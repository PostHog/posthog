"""Conversations' sources for the "For you today" list. Today finds this module by name."""

from products.today.backend.facade.contracts import HighlightSource

from ..today_highlights import find_ticket_sla

HIGHLIGHT_SOURCES = (HighlightSource(name="ticket_sla", find=find_ticket_sla, scopes=("ticket:read",)),)
