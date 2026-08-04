"""Classification of ticket messages by author and visibility.

Shared by the post_save signals and the Celery tasks they hand work to, so both
agree on what counts as private, team-authored, or customer-facing.
"""

from posthog.models.comment import Comment


def is_private_message(item_context: dict | None) -> bool:
    """True for internal notes, which stay invisible to the customer."""
    if not isinstance(item_context, dict):
        return False
    return item_context.get("is_private", False) is True


def comment_created_by_id(comment: Comment) -> int | None:
    created_by_id = getattr(comment, "created_by_id", None)
    return created_by_id if isinstance(created_by_id, int) else None


def is_team_message(item_context: dict | None, created_by_id: int | None) -> bool:
    """True for messages authored by our side: a team member or the AI assistant."""
    if not isinstance(item_context, dict):
        return bool(created_by_id)
    author_type = item_context.get("author_type")
    if created_by_id and author_type != "customer":
        return True
    return author_type == "AI" and not is_private_message(item_context)


def is_outbound_reply(item_context: dict | None, created_by_id: int | None) -> bool:
    """True for messages that should be delivered to the customer's channel.

    This includes human team replies (has created_by, non-customer, non-private) and
    public AI replies (author_type == "AI" with is_private == False).
    """
    if not isinstance(item_context, dict):
        return False
    if is_private_message(item_context):
        return False
    author_type = item_context.get("author_type")
    if created_by_id and author_type != "customer":
        return True
    if author_type == "AI":
        return True
    return False
