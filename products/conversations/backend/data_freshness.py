from datetime import datetime

from django.db.models import Max

from posthog.data_freshness import POSTGRES_TIMEOUT_MS, DataSourceSpec, ProbeWindow
from posthog.models.utils import execute_with_timeout
from posthog.schema_enums import ProductKey

from products.conversations.backend.models.ticket import Ticket


def last_ticket_at(team_ids: list[int], window: ProbeWindow) -> dict[int, datetime]:
    """Tickets touched recently, which is what "support is in use" means.

    `updated_at` rather than `created_at`: a team working its existing queue is using the
    product, and it's the column `posthog_con_team_updated_idx` is built on.
    """
    queryset = (
        Ticket.objects.filter(team_id__in=team_ids, updated_at__gte=window.cutoff, updated_at__lte=window.horizon)
        .values("team_id")
        .annotate(last_at=Max("updated_at"))
    )
    # Evaluated inside the block — the timeout is transaction-local.
    with execute_with_timeout(POSTGRES_TIMEOUT_MS):
        rows = list(queryset)
    return {row["team_id"]: row["last_at"] for row in rows}


DATA_SOURCES = [DataSourceSpec(product=ProductKey.CONVERSATIONS, probe=last_ticket_at)]
