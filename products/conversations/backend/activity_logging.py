from typing import Any

from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.conversations.backend.models.ticket_macro import TicketMacro


@mutable_receiver(model_activity_signal, sender=TicketMacro)
def handle_ticket_macro_change(
    sender: type[TicketMacro],
    scope: str,
    before_update: TicketMacro | None,
    after_update: TicketMacro | None,
    activity: str,
    user: Any,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    macro = after_update if after_update is not None else before_update
    if macro is None:
        return
    # The team reads the activity log, so it never shows the personal side of a macro.
    personal = TicketMacro.Visibility.PERSONAL
    if all(m is None or m.visibility == personal for m in (before_update, after_update)):
        return
    changes = changes_between("TicketMacro", previous=before_update, current=after_update)
    if before_update is not None and after_update is not None and before_update.visibility != after_update.visibility:
        macro = after_update if after_update.visibility != personal else before_update
        changes = [change for change in changes if change.field == "visibility"]
    # Usage bumps go through QuerySet.update, which never reaches this receiver. usage_count and
    # last_used_at are also in signal_exclusions, so a save that only touches them stays quiet.
    log_activity(
        organization_id=macro.team.organization_id,
        team_id=macro.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=macro.id,
        scope=scope,
        activity=activity,
        detail=Detail(changes=changes, name=macro.name),
    )
