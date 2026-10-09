import re

from django.db import migrations
from django.db.models import Q

ATTACHMENT_PURPOSE = "conversations_attachment"
BATCH_SIZE = 200
_MEDIA_ID_RE = re.compile(r"/uploaded_media/([0-9a-fA-F-]{36})")


def tag_legacy_attachments(apps, schema_editor):
    """Tag files that support channels re-hosted before re-hosted files carried a purpose.

    The ticket purge deletes only tagged files, so an untagged attachment outlives its ticket.
    Every channel writes the file link into the message content, so a content match finds it.
    """
    UploadedMedia = apps.get_model("posthog", "UploadedMedia")
    Comment = apps.get_model("posthog", "Comment")

    last_id = None
    while True:
        candidates = UploadedMedia.objects.filter(created_by__isnull=True, purpose__isnull=True)
        if last_id is not None:
            candidates = candidates.filter(id__gt=last_id)
        media_ids = [str(media_id) for media_id in candidates.order_by("id").values_list("id", flat=True)[:BATCH_SIZE]]
        if not media_ids:
            return
        last_id = media_ids[-1]

        # Media ids are random UUIDs, so a link names one file. The scope filter uses the
        # partial trigram index on message content.
        mentions = Q()
        for media_id in media_ids:
            mentions |= Q(content__icontains=f"/uploaded_media/{media_id}")
        contents = (
            Comment.objects.filter(scope="conversations_ticket").filter(mentions).values_list("content", flat=True)
        )
        referenced = {match.lower() for content in contents for match in _MEDIA_ID_RE.findall(content or "")}

        attachment_ids = [media_id for media_id in media_ids if media_id in referenced]
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
