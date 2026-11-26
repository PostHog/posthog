"""DRF serializers for agent_transcripts."""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import MAX_TRANSCRIPT_SIZE_BYTES, MEGABYTE, CustomerSubmissionState, PresignedUpload
from ..facade.enums import SubmissionStatus, TranscriptAgent

MAX_FILENAME_LENGTH = 255


class CustomerSubmissionStateSerializer(DataclassSerializer):
    status = serializers.ChoiceField(
        choices=SubmissionStatus.choices,
        allow_null=True,
        help_text="Where the organization's submission stands. Null when nobody has started an upload.",
    )
    agent = serializers.ChoiceField(
        choices=TranscriptAgent.choices,
        allow_null=True,
        help_text="The AI agent the transcript comes from, as the submitter chose it.",
    )
    original_filename = serializers.CharField(allow_null=True, help_text="Name of the uploaded transcript file.")
    submitted_at = serializers.DateTimeField(
        allow_null=True, help_text="When the last upload passed validation and went to review."
    )
    review_message = serializers.CharField(
        allow_null=True,
        help_text="The reviewer's message to the organization. Set when changes are requested or the "
        "submission is declined.",
    )
    retention_days = serializers.IntegerField(
        help_text="Days after submission that the transcript file is kept before it is deleted."
    )
    max_size_bytes = serializers.IntegerField(help_text="The largest transcript file accepted, in bytes.")
    allowed_extensions = serializers.ListField(
        child=serializers.CharField(),
        help_text="File extensions accepted for a transcript, with the leading dot, for example `.jsonl`.",
    )

    class Meta:
        dataclass = CustomerSubmissionState


class StartUploadRequestSerializer(serializers.Serializer):
    filename = serializers.CharField(
        max_length=MAX_FILENAME_LENGTH,
        help_text="Name of the transcript file. It must end in .jsonl, .json, .md or .txt.",
    )
    size_bytes = serializers.IntegerField(
        help_text=f"Size of the transcript file in bytes, at most {MAX_TRANSCRIPT_SIZE_BYTES // MEGABYTE} MB.",
    )
    agent = serializers.ChoiceField(
        choices=TranscriptAgent.choices,
        help_text="The AI agent the transcript comes from.",
    )


class PresignedUploadSerializer(DataclassSerializer):
    upload_url = serializers.URLField(help_text="POST the file here as multipart/form-data.")
    form_fields = serializers.DictField(
        child=serializers.CharField(),
        help_text="Form fields to send with the file in the same POST, before the file field.",
    )
    expires_in = serializers.IntegerField(help_text="Seconds before the upload URL expires.")

    class Meta:
        dataclass = PresignedUpload


class AgentTranscriptErrorSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="The error class, for example `validation_error`.")
    code = serializers.CharField(help_text="A stable code for the error, for example `contains_secret`.")
    detail = serializers.CharField(help_text="What went wrong and what to do next.")
    attr = serializers.CharField(allow_null=True, help_text="The request field the error is about, if any.")
