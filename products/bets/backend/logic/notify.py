from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    TargetType,
    create_notification,
)

from ..db import WRITER_DB
from ..models import Bet
from .state import bet_state


def notify_owner(bet: Bet) -> None:
    actions = bet_state(bet).actions
    current = [item["id"] for item in actions]
    for item in actions:
        if item["id"] in bet.notified_actions:
            continue
        create_notification(
            NotificationData(
                team_id=bet.team_id,
                notification_type=NotificationType.APPROVAL_REQUESTED,
                title=f"{bet.title}: {item['title']}",
                body=item["description"],
                target_type=TargetType.USER,
                target_id=str(bet.owner_id),
                resource_id=str(bet.id),
                source_url=f"/bets/{bet.id}",
            )
        )
    if current != bet.notified_actions:
        bet.notified_actions = current
        bet.save(using=WRITER_DB, update_fields=["notified_actions", "updated_at"])
