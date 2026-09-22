"""The platform's write, as its own activity.

A source's evaluation reads and decides; this records. Splitting them is what makes an
evaluation replayable: it touches nothing, so a worker that dies before Temporal accepts its
result loses nothing but the queries. By the time this runs, the deliveries the batch decided
on are already in the workflow's history.

A source starts this by name rather than importing it, which keeps the products apart and keeps
this module off the import path of any workflow.
"""

import datetime as dt

from temporalio import activity
from temporalio.exceptions import ApplicationError

from products.alerts.backend.facade.contracts import RECORD_OUTCOMES_ACTIVITY, SourceOutcomeInputs
from products.alerts.backend.temporal.metrics import increment_outcomes_recorded, safe_record

WRITE_PERMISSION_DENIED = "AlertsProductWritePermissionDenied"
# Postgres `insufficient_privilege`.
PERMISSION_DENIED_SQLSTATE = "42501"


@activity.defn(name=RECORD_OUTCOMES_ACTIVITY)
async def alerts_product_record_outcomes_activity(inputs: SourceOutcomeInputs) -> int:
    """Records one batch's decisions. Returns how many reached the tables."""
    # Imported in the activity body, not at module scope: a Django model import trips Temporal's
    # workflow sandbox, and the worker registration that reaches this module runs through one.
    from django.db import DatabaseError

    from posthog.models import Team
    from posthog.sync import database_sync_to_async_pool

    from products.alerts.backend.facade.platform_alerts import record_outcomes

    if not inputs.outcomes:
        return 0

    def _record() -> int:
        timezone = Team.objects.filter(id=inputs.team_id).values_list("timezone", flat=True).first()
        if timezone is None:
            return 0
        return record_outcomes(
            inputs.team_id,
            inputs.outcomes,
            dt.datetime.fromisoformat(inputs.cutoff),
            team_timezone=timezone,
        )

    try:
        recorded = await database_sync_to_async_pool(_record)()
    except DatabaseError as error:
        if getattr(error.__cause__, "sqlstate", None) != PERMISSION_DENIED_SQLSTATE:
            raise
        # The grant is missing for every attempt of every batch, so retrying only multiplies the
        # same failure. Fail the batch once; its keys stay due for a later tick.
        raise ApplicationError(
            "The database role cannot write the shared alert tables",
            type=WRITE_PERMISSION_DENIED,
            non_retryable=True,
        ) from None
    safe_record(increment_outcomes_recorded, recorded)
    return recorded
