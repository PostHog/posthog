from uuid import UUID

from django.db import models
from django.db.models.fields.json import JSONField
from django.db.models.functions import Coalesce

from posthog.models.comment import Comment


def set_comment_delivery_status(team_id: int, comment_id: UUID, status_value: str) -> None:
    """Denormalize delivery status onto the comment's item_context so the agent UI can
    show a sending/delivered/failed badge. Uses a queryset update to avoid re-firing
    Comment signals.

    Merges at the DB level (JSONB ``||``) rather than read-modify-write: a concurrent
    edit to another key (e.g. an agent flipping ``is_private``) must not be clobbered.
    The dict values flow through ORM ``Value`` params, so this is fully parameterized.
    """
    merged = models.Func(
        Coalesce("item_context", models.Value({}, output_field=JSONField())),
        models.Value({"email_delivery_status": status_value}, output_field=JSONField()),
        template="%(expressions)s",
        arg_joiner=" || ",
        output_field=JSONField(),
    )
    Comment.objects.filter(id=comment_id, team_id=team_id).update(item_context=merged)
