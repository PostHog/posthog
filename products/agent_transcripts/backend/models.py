from django.db import models

from posthog.models.utils import UUIDModel

from .facade.contracts import MERCH_CODE_MAX_LENGTH
from .facade.enums import SubmissionStatus, TranscriptAgent


class AgentTranscriptSubmission(UUIDModel):
    """An organization's transcript of its signup conversation with an AI agent, and the staff review of it.

    An organization has at most one row, ever. A resubmission after `changes_requested` reuses the row
    and replaces the file. `approved` and `declined` are final.
    """

    # db_constraint=False keeps CreateModel off posthog_organization's lock path, which is a hot table.
    # The one-to-one still makes the row unique per organization.
    organization = models.OneToOneField(
        "posthog.Organization",
        on_delete=models.CASCADE,
        db_constraint=False,
        related_name="+",
    )
    status = models.CharField(
        max_length=32,
        choices=SubmissionStatus.choices,
        default=SubmissionStatus.PENDING_UPLOAD.value,
    )
    agent = models.CharField(max_length=32, choices=TranscriptAgent.choices)

    original_filename = models.CharField(max_length=255)
    # The key of the last upload that passed validation. A new upload replaces it on completion.
    storage_key = models.CharField(max_length=1024, null=True, blank=True)
    # The only key a presigned upload form is signed for. That form stays valid until it expires, so
    # validated bytes move to `storage_key`, a key no upload form was ever signed for.
    staging_key = models.CharField(max_length=1024, null=True, blank=True)
    size_bytes = models.PositiveIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=64, null=True, blank=True)

    submitted_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)

    reviewed_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(null=True, blank=True)
    review_message = models.TextField(null=True, blank=True)

    merch_code = models.CharField(max_length=MERCH_CODE_MAX_LENGTH, null=True, blank=True, unique=True)

    file_deleted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
