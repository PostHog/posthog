from uuid import UUID

from django.db import transaction

from posthog.models.comment import Comment

from products.conversations.backend.models.email_thread import (
    EMAIL_THREAD_COMMENT_SCOPE,
    EmailThread,
    EmailThreadMessage,
)


@transaction.atomic
def delete_email_thread(*, team_id: int, thread_id: UUID | str) -> None:
    thread = EmailThread.objects.for_team(team_id).select_for_update().get(id=thread_id)

    EmailThreadMessage.objects.for_team(team_id).filter(thread=thread).delete()
    Comment.objects.filter(
        team_id=team_id,
        scope=EMAIL_THREAD_COMMENT_SCOPE,
        item_id=str(thread.id),
    ).delete()
    thread.delete()
