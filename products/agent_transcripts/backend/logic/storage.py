"""Object storage for transcripts. Keys live under one prefix, which a bucket lifecycle rule expires."""

from uuid import UUID, uuid4

from django.conf import settings

import structlog

from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

from ..facade.contracts import MAX_TRANSCRIPT_SIZE_BYTES, PresignedUpload, TranscriptStorageUnavailable
from . import content

logger = structlog.get_logger(__name__)

UPLOAD_URL_EXPIRATION_SECONDS = 15 * 60
DOWNLOAD_URL_EXPIRATION_SECONDS = 60
STAGING_SEGMENT = "staging"


def build_staging_key(organization_id: UUID) -> str:
    """The only key a presigned upload form is signed for. Validated bytes move to `build_storage_key`."""
    return "/".join(
        [settings.OBJECT_STORAGE_AGENT_TRANSCRIPTS_FOLDER, str(organization_id), STAGING_SEGMENT, str(uuid4())]
    )


def build_storage_key(organization_id: UUID, filename: str) -> str:
    return "/".join(
        [
            settings.OBJECT_STORAGE_AGENT_TRANSCRIPTS_FOLDER,
            str(organization_id),
            str(uuid4()),
            content.storage_filename(filename),
        ]
    )


def presign_upload(key: str) -> PresignedUpload:
    presigned_post = object_storage.get_presigned_post(
        key,
        conditions=[["content-length-range", content.MIN_TRANSCRIPT_SIZE_BYTES, MAX_TRANSCRIPT_SIZE_BYTES]],
        expiration=UPLOAD_URL_EXPIRATION_SECONDS,
    )
    if not presigned_post:
        raise TranscriptStorageUnavailable("Could not create an upload URL")

    return PresignedUpload(
        upload_url=presigned_post["url"],
        form_fields=presigned_post["fields"],
        expires_in=UPLOAD_URL_EXPIRATION_SECONDS,
    )


def presign_download(key: str, filename: str) -> str | None:
    return object_storage.get_presigned_url(
        key,
        expiration=DOWNLOAD_URL_EXPIRATION_SECONDS,
        content_type=content.content_type_for(filename),
        content_disposition=f'attachment; filename="{content.storage_filename(filename)}"',
    )


def object_size(key: str) -> int | None:
    """The stored size in bytes, or None when nothing is stored at the key."""
    try:
        head = object_storage.head_object_strict(key)
    except ObjectStorageError as error:
        raise TranscriptStorageUnavailable("Could not read the uploaded file") from error

    return None if head is None else int(head["ContentLength"])


def read(key: str) -> bytes | None:
    try:
        return object_storage.read_bytes(key, missing_ok=True)
    except ObjectStorageError as error:
        raise TranscriptStorageUnavailable("Could not read the uploaded file") from error


def write(key: str, data: bytes, content_type: str) -> None:
    try:
        object_storage.write(key, data, extras={"ContentType": content_type})
    except ObjectStorageError as error:
        raise TranscriptStorageUnavailable("Could not store the uploaded file") from error


def delete(key: str) -> None:
    try:
        object_storage.delete(key)
    except ObjectStorageError as error:
        raise TranscriptStorageUnavailable("Could not delete the transcript") from error


def delete_quietly(key: str) -> None:
    """Delete an object that nothing references any more. The lifecycle rule removes it if this fails."""
    try:
        object_storage.delete(key)
    except ObjectStorageError:
        logger.warning("agent_transcripts.object_delete_failed", key=key, exc_info=True)
