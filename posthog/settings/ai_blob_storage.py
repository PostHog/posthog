import os
from typing import Optional

from posthog.settings.base_variables import DEBUG, TEST

# AI blob storage uses a separate bucket from general object storage
# These settings match the capture service's AI S3 configuration

if TEST or DEBUG:
    AI_S3_ENDPOINT: Optional[str] = os.getenv("AI_S3_ENDPOINT", "http://localhost:19000")
    AI_S3_ACCESS_KEY_ID: Optional[str] = os.getenv("AI_S3_ACCESS_KEY_ID", "object_storage_root_user")
    AI_S3_SECRET_ACCESS_KEY: Optional[str] = os.getenv("AI_S3_SECRET_ACCESS_KEY", "object_storage_root_password")
else:
    AI_S3_ENDPOINT: Optional[str] = os.getenv("AI_S3_ENDPOINT") or None
    AI_S3_ACCESS_KEY_ID: Optional[str] = os.getenv("AI_S3_ACCESS_KEY_ID") or None
    AI_S3_SECRET_ACCESS_KEY: Optional[str] = os.getenv("AI_S3_SECRET_ACCESS_KEY") or None

AI_S3_BUCKET: Optional[str] = os.getenv("AI_S3_BUCKET", "ai-blobs" if (TEST or DEBUG) else None)
AI_S3_REGION: str = os.getenv("AI_S3_REGION", "us-east-1")
AI_S3_PREFIX: str = os.getenv("AI_S3_PREFIX", "llma/")

# TTL for presigned URLs in seconds (1 hour default)
AI_BLOB_PRESIGNED_TTL_SECONDS: int = int(os.getenv("AI_BLOB_PRESIGNED_TTL_SECONDS", "3600"))
