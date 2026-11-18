import re
from datetime import datetime, timedelta

from django.db import migrations
from django.db.models import Q

ATTACHMENT_PURPOSE = "conversations_attachment"
BATCH_SIZE = 200
# A channel downloads every file of a message before it inserts the message. A long Slack
# thread backfill re-hosts all of its files first, so the window is wide.
REHOST_WINDOW = timedelta(hours=1)
_MEDIA_ID_RE = re.compile(r"/uploaded_media/([0-9a-fA-F-]{36})")


def _was_rehosted_for(media_created_at: datetime, comment_created_at: datetime, *, from_zendesk: bool) -> bool:
    if comment_created_at - REHOST_WINDOW <= media_created_at <= comment_created_at:
        return True
    # The Zendesk import keeps the original message time and re-hosts the file later. A sender
    # can only link a file that already exists, so a linked file is never newer than the message.
    return from_zendesk and media_created_at >= comment_created_at


def tag_legacy_attachments(apps, schema_editor):
    """Tag files that support channels re-hosted before re-hosted files carried a purpose.

    The ticket purge deletes only tagged files, so an untagged attachment outlives its ticket.
    Every channel writes the file link into the message content, so a content match finds it.
    A link alone does not prove that a channel created the file: a sender can paste the link
    of another team file. The file must also be created at the time a channel re-hosts it.
    """
    UploadedMedia = apps.get_model("posthog", "UploadedMedia")
    Comment = apps.get_model("posthog", "Comment")

    last_id = None
    while True:
        candidates = UploadedMedia.objects.filter(created_by__isnull=True, purpose__isnull=True)
        if last_id is not None:
            candidates = candidates.filter(id__gt=last_id)
        media_rows = list(candidates.order_by("id").values_list("id", "created_at")[:BATCH_SIZE])
        if not media_rows:
            return
        last_id = media_rows[-1][0]
        media_created_at = {str(media_id): created_at for media_id, created_at in media_rows}

        # Media ids are random UUIDs, so a link names one file. The scope filter uses the
        # partial trigram index on message content.
        mentions = Q()
        for media_id in media_created_at:
            mentions |= Q(content__icontains=f"/uploaded_media/{media_id}")
        comments = (
            Comment.objects.filter(scope="conversations_ticket")
            .filter(mentions)
            .values_list("content", "created_at", "item_context")
        )

        attachment_ids: set[str] = set()
        for content, comment_created_at, item_context in comments:
            from_zendesk = isinstance(item_context, dict) and item_context.get("from_zendesk") is True
            for match in _MEDIA_ID_RE.findall(content or ""):
                media_id = match.lower()
                created_at = media_created_at.get(media_id)
                if created_at is not None and _was_rehosted_for(
                    created_at, comment_created_at, from_zendesk=from_zendesk
                ):
                    attachment_ids.add(media_id)
        if attachment_ids:
            UploadedMedia.objects.filter(id__in=attachment_ids, purpose__isnull=True).update(purpose=ATTACHMENT_PURPOSE)


class Migration(migrations.Migration):
    # Each batch commits on its own, so the backfill never holds row locks in one long transaction.
    # A retry is safe: tagged rows no longer match the candidate filter.
    atomic = False

    dependencies = [
        ("conversations", "0075_purgedticketthread"),
    ]

    operations = [
        migrations.RunPython(tag_legacy_attachments, migrations.RunPython.noop),
    ]
