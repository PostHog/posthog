from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings

import structlog

from posthog.cdp.internal_events import InternalEventEvent, InternalEventPerson, produce_internal_event
from posthog.exceptions_capture import capture_exception
from posthog.models import User

if TYPE_CHECKING:
    from posthog.models.comment import Comment

logger = structlog.get_logger(__name__)

SCOPE_TO_PATH_MAPPING: dict[str, str] = {
    "Replay": "/replay/{item_id}",
    "Notebook": "/notebooks/{item_id}",
    "Insight": "/insights/{item_id}",
    "FeatureFlag": "/feature_flags/{item_id}",
    "Dashboard": "/dashboard/{item_id}",
    "Survey": "/surveys/{item_id}",
    "Experiment": "/experiments/{item_id}",
}

TICKET_COMMENT_SCOPES = {"conversations_ticket", "Ticket"}


def is_ticket_comment_scope(scope: str) -> bool:
    return scope in TICKET_COMMENT_SCOPES


def _get_user_display_name(user: User) -> str:
    first_name = (user.first_name or "").strip()
    if first_name:
        return first_name

    if user.email:
        return user.email.split("@")[0]

    return f"user:{user.id}"


def build_mention_display_name_lookup(user_ids: Iterable[int]) -> dict[int, str]:
    unique_user_ids = set(user_ids)
    if not unique_user_ids:
        return {}

    mentioned_users = User.objects.filter(id__in=unique_user_ids).only("id", "first_name", "email")
    return {mentioned_user.id: _get_user_display_name(mentioned_user) for mentioned_user in mentioned_users}


def build_comment_item_url(
    scope: str, item_id: Optional[str], slug: Optional[str] = None, team_id: Optional[int] = None
) -> str:
    if slug:
        url = f"{settings.SITE_URL}{slug}"
    elif is_ticket_comment_scope(scope) and item_id and team_id is not None:
        url = f"{settings.SITE_URL}/project/{team_id}/conversations/tickets/{item_id}"
    elif scope in SCOPE_TO_PATH_MAPPING and item_id:
        path = SCOPE_TO_PATH_MAPPING[scope].format(item_id=item_id)
        url = f"{settings.SITE_URL}{path}"
    else:
        url = settings.SITE_URL

    if is_ticket_comment_scope(scope):
        url = url.split("#", 1)[0]

    should_append_discussion_panel = not is_ticket_comment_scope(scope) and "/conversations/tickets/" not in url
    if should_append_discussion_panel and "#panel=discussion" not in url:
        url = f"{url}#panel=discussion"

    return url


def extract_plain_text_from_rich_content(
    rich_content: Optional[dict], mention_display_names: Optional[dict[int, str]] = None
) -> str:
    if not rich_content:
        return ""

    text_parts: list[str] = []

    def traverse(node: Any) -> None:
        if isinstance(node, dict):
            node_type = node.get("type")
            if node_type == "text":
                text_parts.append(node.get("text", ""))
            elif node_type == "ph-mention":
                attrs = node.get("attrs", {})
                label = attrs.get("label", "")
                mention_id = attrs.get("id")
                if label:
                    text_parts.append(f"@{label}")
                elif isinstance(mention_id, int):
                    mention_display_name = mention_display_names.get(mention_id) if mention_display_names else None
                    text_parts.append(f"@{mention_display_name}" if mention_display_name else f"@member:{mention_id}")
            elif node_type == "hardBreak":
                text_parts.append("\n")

            for value in node.values():
                if isinstance(value, dict | list):
                    traverse(value)
        elif isinstance(node, list):
            for item in node:
                traverse(item)

    traverse(rich_content)
    return "".join(text_parts)


def produce_discussion_mention_events(
    comment: "Comment",
    mentioned_user_ids: list[int],
    slug: str,
) -> None:
    try:
        commenter = comment.created_by
        if not commenter:
            return

        mentioned_users = list(User.objects.filter(id__in=mentioned_user_ids).exclude(id=commenter.id))
        if not mentioned_users:
            return

        mention_display_names = {
            mentioned_user.id: _get_user_display_name(mentioned_user) for mentioned_user in mentioned_users
        }
        item_url = build_comment_item_url(comment.scope, comment.item_id, slug, team_id=comment.team_id)
        comment_content = (
            extract_plain_text_from_rich_content(comment.rich_content, mention_display_names) or comment.content
        )

        commenter_data = {
            "id": str(commenter.id),
            "distinct_id": commenter.distinct_id,
            "email": commenter.email,
            "first_name": commenter.first_name,
        }

        for mentioned_user in mentioned_users:
            produce_internal_event(
                team_id=comment.team_id,
                event=InternalEventEvent(
                    event="$discussion_mention_created",
                    distinct_id=commenter.distinct_id or f"user_{commenter.id}",
                    properties={
                        "mentioned_user_id": mentioned_user.id,
                        "mentioned_user_email": mentioned_user.email,
                        "mentioned_user_name": mentioned_user.first_name,
                        "commenter_user_id": commenter.id,
                        "commenter_user_email": commenter.email,
                        "commenter_user_name": commenter.first_name,
                        "comment_content": comment_content,
                        "item_url": item_url,
                        "slug": slug,
                        "scope": comment.scope,
                        "item_id": comment.item_id,
                        "team_name": comment.team.name,
                        "project_id": comment.team.project_id,
                    },
                ),
                person=InternalEventPerson(
                    id=str(commenter.id),
                    properties=commenter_data,
                ),
            )
    except Exception as e:
        logger.exception("Failed to produce discussion mention events", error=e)
        capture_exception(e)
