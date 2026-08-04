from datetime import datetime

from posthog.data_freshness import POSTGRES_TIMEOUT_MS, DataSourceSpec, ProbeWindow
from posthog.models.utils import execute_with_timeout
from posthog.schema_enums import ProductKey

from products.conversations.backend.models.ticket import Ticket


def last_ticket_at(team_ids: list[int], window: ProbeWindow) -> dict[int, datetime]:
    """Tickets touched recently, which is what "support is in use" means.

    `updated_at` rather than `created_at`: a team working its existing queue is using the product,
    and it's the column `posthog_con_team_updated_idx` is built on.

    One indexed lookup per team rather than a grouped `Max`. Grouping blocks Postgres's
    backward-index-scan rewrite, so it would read every ticket in the window — the whole recent
    queue for a busy team — to take one row from each.
    """
    found: dict[int, datetime] = {}
    with execute_with_timeout(POSTGRES_TIMEOUT_MS):
        for team_id in team_ids:
            last_at = (
                Ticket.objects.filter(team_id=team_id, updated_at__gte=window.cutoff, updated_at__lte=window.horizon)
                .order_by("-updated_at")
                .values_list("updated_at", flat=True)
                .first()
            )
            if last_at is not None:
                found[team_id] = last_at
    return found


DATA_SOURCES = [DataSourceSpec(product=ProductKey.CONVERSATIONS, probe=last_ticket_at)]
