from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.utils import UUIDTModel, sane_repr


class DuckLakeCatalog(UUIDTModel):
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

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_ducklakecatalog"
        verbose_name = "DuckLake catalog"
        verbose_name_plural = "DuckLake catalogs"

    __repr__ = sane_repr("team_id", "rds_host", "bucket")

    def __str__(self) -> str:
        return f"DuckLakeCatalog(team_id={self.team_id}, host={self.rds_host}, bucket={self.bucket})"

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
