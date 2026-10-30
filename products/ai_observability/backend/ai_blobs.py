"""`phaiblob://` pointers that ingestion writes in place of offloaded AI media. Twin of `frontend/aiBlob.ts`."""

import re
from urllib.parse import parse_qs

from django.conf import settings

from posthog.dataclasses import frozen
from posthog.storage import object_storage

_POINTER_RE = re.compile(r"^phaiblob://v1/sha256/([0-9a-f]{64})(?:\?(.*))?$")


def blob_key(team_id: int, sha256: str) -> str:
    return f"{settings.AI_BLOB_S3_PREFIX}{team_id}/sha256/{sha256}"


@frozen
class BlobPointer:
    sha256: str
    mime_type: str | None = None

    @classmethod
    def parse(cls, value: str) -> "BlobPointer | None":
        match = _POINTER_RE.match(value)
        if match is None:
            return None
        # The pointer's `size=` comes from event data, so readers ask storage for the real size instead.
        mime_type = parse_qs(match.group(2) or "").get("mime", [None])[0]
        return cls(sha256=match.group(1), mime_type=mime_type)

    # The team id always comes from the caller's own scope, never from event data,
    # so a pointer copied from another team's event can't reach that team's blob.
    def read(self, team_id: int) -> bytes | None:
        return object_storage.read_bytes(
            blob_key(team_id, self.sha256), bucket=settings.AI_BLOB_S3_BUCKET, missing_ok=True
        )

    def stored_size(self, team_id: int) -> int | None:
        head = object_storage.head_object_strict(blob_key(team_id, self.sha256), bucket=settings.AI_BLOB_S3_BUCKET)
        return int(head["ContentLength"]) if head else None

    def presigned_url(self, team_id: int, expiration_seconds: int) -> str | None:
        return object_storage.get_presigned_url(
            blob_key(team_id, self.sha256), expiration=expiration_seconds, bucket=settings.AI_BLOB_S3_BUCKET
        )
