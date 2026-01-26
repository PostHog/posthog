from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

if TYPE_CHECKING:
    from posthog.ducklake.storage import CrossAccountDestination


class DuckLakeCatalog(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """Per-team DuckLake catalog configuration.

    Stores RDS connection details and bucket configuration for teams that need
    isolated DuckLake catalogs (e.g., single-tenant Duckling customers).

    For teams without a DuckLakeCatalog entry, the system falls back to
    environment variable configuration.
    """

    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="ducklake_catalog",
    )

    # RDS connection settings
    rds_host = models.CharField(max_length=255)
    rds_port = models.IntegerField(default=5432)
    rds_database = models.CharField(max_length=255, default="ducklake")
    rds_username = models.CharField(max_length=255)
    rds_password = EncryptedTextField(max_length=500)

    # Bucket settings (no secrets - credentials come from IRSA or storage.py)
    bucket = models.CharField(max_length=255)
    bucket_region = models.CharField(max_length=50, default="us-east-1")

    # Cross-account S3 access settings (required - for writing to customer-owned buckets)
    cross_account_role_arn = models.CharField(
        max_length=255,
        help_text="ARN of the IAM role to assume for cross-account S3 access",
    )
    cross_account_external_id = models.CharField(
        max_length=255,
        help_text="External ID for cross-account role assumption",
    )

    class Meta:
        db_table = "posthog_ducklakecatalog"
        verbose_name = "DuckLake catalog"
        verbose_name_plural = "DuckLake catalogs"

    def to_config(self) -> dict[str, str]:
        """Convert to a config dict compatible with get_config()."""
        return {
            "DUCKLAKE_RDS_HOST": self.rds_host,
            "DUCKLAKE_RDS_PORT": str(self.rds_port),
            "DUCKLAKE_RDS_DATABASE": self.rds_database,
            "DUCKLAKE_RDS_USERNAME": self.rds_username,
            "DUCKLAKE_RDS_PASSWORD": self.rds_password,
            "DUCKLAKE_BUCKET": self.bucket,
            "DUCKLAKE_BUCKET_REGION": self.bucket_region,
            # S3 credentials are not stored per-team; they come from environment or IRSA
            "DUCKLAKE_S3_ACCESS_KEY": "",
            "DUCKLAKE_S3_SECRET_KEY": "",
        }

    def to_cross_account_destination(self) -> CrossAccountDestination:
        """Convert to a CrossAccountDestination for cross-account S3 access."""
        from posthog.ducklake.storage import CrossAccountDestination

        return CrossAccountDestination(
            role_arn=self.cross_account_role_arn,
            bucket_name=self.bucket,
            external_id=self.cross_account_external_id,
            region=self.bucket_region or None,
        )
