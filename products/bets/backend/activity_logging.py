from typing import TYPE_CHECKING

from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.team import Team

from .db import WRITER_DB
from .models import Bet

if TYPE_CHECKING:
    from posthog.models.user import User


@mutable_receiver(model_activity_signal, sender=Bet)
def handle_bet_change(
    sender: type[Bet],
    before_update: Bet | None,
    after_update: Bet | None,
    activity: str,
    user: "User | None",
    was_impersonated: bool = False,
    **kwargs: object,
) -> None:
    instance = after_update or before_update
    if instance is None:
        return
    log_activity(
        organization_id=Team.objects.values_list("organization_id", flat=True).get(id=instance.team_id),
        team_id=instance.team_id,
        user=user,
        item_id=instance.id,
        scope="Bet",
        activity=activity,
        detail=Detail(
            name=instance.title, changes=changes_between("Bet", previous=before_update, current=after_update)
        ),
        was_impersonated=was_impersonated,
        using=WRITER_DB,
    )
