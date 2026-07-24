"""Activity-log hook for KnowledgeSource create/update/delete."""

import dataclasses
from typing import Any

import structlog

from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    ActivityScope,
    Detail,
    changes_between,
    log_activity,
)
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User

from .models import KnowledgeSource

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class KnowledgeSourceContext(ActivityContextBase):
    team_id: int
    source_type: str
    name: str


@mutable_receiver(model_activity_signal, sender=KnowledgeSource)
def handle_knowledge_source_change(
    sender: type[KnowledgeSource],
    scope: ActivityScope,
    before_update: KnowledgeSource | None,
    after_update: KnowledgeSource | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance: KnowledgeSource | None = after_update or before_update
    if instance is None:
        return

    context = KnowledgeSourceContext(
        team_id=instance.team_id,
        source_type=instance.source_type,
        name=instance.name,
    )

    if activity == "created":
        detail_name = f"Knowledge source '{instance.name}' added"
    elif activity == "deleted":
        detail_name = f"Knowledge source '{instance.name}' deleted"
    else:
        detail_name = f"Knowledge source '{instance.name}' updated"

    log_activity(
        organization_id=None,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=detail_name,
            context=context,
        ),
    )
