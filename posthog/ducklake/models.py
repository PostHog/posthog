"""Django models for per-team DuckLake catalog configuration.

DuckLakeCatalog stores the configuration needed to connect to a customer's
dedicated "duckling" - their isolated DuckLake instance with its own:
- RDS PostgreSQL catalog database
- S3 bucket for data storage
- Cross-account IAM role for access
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from django.db import models

if TYPE_CHECKING:
    pass


@dataclasses.dataclass(frozen=True)
class CrossAccountDestination:
    """Configuration for cross-account S3 access via IAM role assumption.

    Used to access a customer's S3 bucket in their AWS account by assuming
    an IAM role with an external ID for security.
    """

    role_arn: str
    external_id: str
    bucket: str
    region: str

    def get_s3_base_path(self) -> str:
        """Return the S3 base path for this destination."""
        return f"s3://{self.bucket}/"


class DuckLakeCatalog(models.Model):
    """Per-team DuckLake catalog configuration for customer ducklings.

    Each record represents a customer's dedicated DuckLake instance ("duckling"),
    containing the connection details for their isolated data warehouse.

    The catalog stores:
    - RDS connection info for the DuckLake PostgreSQL catalog
    - S3 bucket location for data storage
    - Cross-account IAM role for secure access from PostHog's AWS account
    """

    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="ducklake_catalog",
        help_text="Team that owns this duckling instance",
    )

    # RDS catalog connection
    rds_host = models.CharField(
        max_length=255,
        help_text="RDS PostgreSQL host for the DuckLake catalog",
    )
    rds_port = models.IntegerField(
        default=5432,
        help_text="RDS PostgreSQL port",
    )
    rds_database = models.CharField(
        max_length=63,
        default="ducklake",
        help_text="Database name for the DuckLake catalog",
    )
    rds_username = models.CharField(
        max_length=63,
        help_text="Database username",
    )
    rds_password = models.CharField(
        max_length=255,
        help_text="Database password (encrypted at rest)",
    )

    # S3 storage configuration
    s3_bucket = models.CharField(
        max_length=63,
        help_text="S3 bucket for DuckLake data storage",
    )
    s3_region = models.CharField(
        max_length=32,
        default="us-east-1",
        help_text="AWS region for the S3 bucket",
    )

    # Cross-account access (for PostHog prod to access customer's AWS account)
    cross_account_role_arn = models.CharField(
        max_length=255,
        help_text="IAM role ARN to assume for cross-account access",
    )
    cross_account_external_id = models.CharField(
        max_length=255,
        help_text="External ID for secure role assumption",
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "DuckLake Catalog"
        verbose_name_plural = "DuckLake Catalogs"
        app_label = "posthog"

    def __str__(self) -> str:
        return f"DuckLakeCatalog(team_id={self.team_id}, bucket={self.s3_bucket})"

    def get_catalog_connection_string(self) -> str:
        """Build the DuckLake catalog connection string for DuckDB."""
        return (
            f"postgres:dbname={self.rds_database} "
            f"host={self.rds_host} "
            f"port={self.rds_port} "
            f"user={self.rds_username} "
            f"password={self.rds_password}"
        )

    def get_data_path(self) -> str:
        """Get the S3 data path for this duckling."""
        return f"s3://{self.s3_bucket}/"

    def to_cross_account_destination(self) -> CrossAccountDestination:
        """Create a CrossAccountDestination for this catalog's S3 bucket."""
        return CrossAccountDestination(
            role_arn=self.cross_account_role_arn,
            external_id=self.cross_account_external_id,
            bucket=self.s3_bucket,
            region=self.s3_region,
        )

    def to_config_dict(self) -> dict[str, str]:
        """Return a config dict compatible with ducklake.common functions."""
        return {
            "DUCKLAKE_RDS_HOST": self.rds_host,
            "DUCKLAKE_RDS_PORT": str(self.rds_port),
            "DUCKLAKE_RDS_DATABASE": self.rds_database,
            "DUCKLAKE_RDS_USERNAME": self.rds_username,
            "DUCKLAKE_RDS_PASSWORD": self.rds_password,
            "DUCKLAKE_BUCKET": self.s3_bucket,
            "DUCKLAKE_BUCKET_REGION": self.s3_region,
        }


def get_team_catalog(team_id: int) -> DuckLakeCatalog | None:
    """Look up the DuckLakeCatalog for a team.

    Args:
        team_id: The team ID to look up.

    Returns:
        DuckLakeCatalog if one exists for this team, None otherwise.
    """
    try:
        return DuckLakeCatalog.objects.get(team_id=team_id)
    except DuckLakeCatalog.DoesNotExist:
        return None
