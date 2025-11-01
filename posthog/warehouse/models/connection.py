from typing import Any
from django.db import models
from django.utils import timezone
import structlog

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr

logger = structlog.get_logger(__name__)


class WarehouseConnection(CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    """Warehouse connection configuration for direct querying

    This model stores connection details for external data warehouses like
    BigQuery, Snowflake, Redshift, and Databricks, allowing PostHog to
    query them directly without syncing data to S3/ClickHouse.
    """

    PROVIDER_BIGQUERY = "bigquery"
    PROVIDER_SNOWFLAKE = "snowflake"
    PROVIDER_REDSHIFT = "redshift"
    PROVIDER_DATABRICKS = "databricks"

    PROVIDER_CHOICES = [
        (PROVIDER_BIGQUERY, "BigQuery"),
        (PROVIDER_SNOWFLAKE, "Snowflake"),
        (PROVIDER_REDSHIFT, "Redshift"),
        (PROVIDER_DATABRICKS, "Databricks"),
    ]

    MODE_SYNC = "sync"
    MODE_DIRECT = "direct"
    MODE_HYBRID = "hybrid"

    MODE_CHOICES = [
        (MODE_SYNC, "Sync to ClickHouse"),
        (MODE_DIRECT, "Query directly"),
        (MODE_HYBRID, "Hybrid (cached)"),
    ]

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, help_text="Human-readable name for this connection")
    provider = models.CharField(max_length=50, choices=PROVIDER_CHOICES)
    credentials = EncryptedJSONField(
        help_text="Encrypted credentials for warehouse connection"
    )
    mode = models.CharField(
        max_length=20,
        choices=MODE_CHOICES,
        default=MODE_SYNC,
        help_text="Query mode: sync (copy to ClickHouse), direct (query warehouse), or hybrid (cached)",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this connection is active and should be used",
    )
    config = models.JSONField(
        default=dict,
        help_text="Configuration options like timeout, cache_ttl, etc.",
    )
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    last_tested_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this connection was last tested",
    )
    last_test_status = models.BooleanField(
        default=False,
        help_text="Result of last connection test",
    )
    last_test_error = models.TextField(
        null=True,
        blank=True,
        help_text="Error message from last failed connection test",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"], name="unique_warehouse_connection_name_per_team"
            )
        ]
        indexes = [
            models.Index(fields=["team", "is_active"]),
            models.Index(fields=["team", "provider"]),
        ]

    __repr__ = sane_repr("name", "provider", "mode")

    def get_connector(self):
        """Return appropriate connector instance for this connection

        Returns:
            BaseWarehouseConnector instance

        Raises:
            ValueError: If provider is unknown or credentials are invalid
            ImportError: If required connector package is not installed
        """
        from posthog.warehouse.connectors import get_connector

        return get_connector(
            credentials=self.credentials,
            config=self.config,
            provider=self.provider,
        )

    def test_connection(self, save_result: bool = True) -> tuple[bool, str | None]:
        """Test connection and optionally update status

        Args:
            save_result: Whether to save test result to database

        Returns:
            Tuple of (success: bool, error_message: str | None)
        """
        try:
            connector = self.get_connector()
            success = connector.test_connection()
            connector.close()

            if save_result:
                self.last_test_status = success
                self.last_tested_at = timezone.now()
                if success:
                    self.last_test_error = None
                else:
                    self.last_test_error = "Connection test returned false"
                self.save(update_fields=["last_test_status", "last_tested_at", "last_test_error"])

            logger.info(
                "Warehouse connection test completed",
                connection_id=self.id,
                connection_name=self.name,
                provider=self.provider,
                success=success,
            )

            return (success, None if success else "Connection test failed")

        except Exception as e:
            error_message = str(e)

            if save_result:
                self.last_test_status = False
                self.last_tested_at = timezone.now()
                self.last_test_error = error_message
                self.save(update_fields=["last_test_status", "last_tested_at", "last_test_error"])

            logger.error(
                "Warehouse connection test failed",
                connection_id=self.id,
                connection_name=self.name,
                provider=self.provider,
                error=error_message,
            )

            return (False, error_message)

    def get_default_timeout(self) -> int:
        """Get default query timeout in seconds based on mode"""
        if self.mode == self.MODE_DIRECT:
            return 300
        elif self.mode == self.MODE_HYBRID:
            return 60
        else:
            return 300

    def get_default_cache_ttl(self) -> int:
        """Get default cache TTL in seconds based on mode"""
        if self.mode == self.MODE_DIRECT:
            return 0
        elif self.mode == self.MODE_HYBRID:
            return 3600
        else:
            return 0

    @property
    def timeout_seconds(self) -> int:
        """Get query timeout in seconds from config or default"""
        return self.config.get("timeout_seconds", self.get_default_timeout())

    @property
    def cache_ttl_seconds(self) -> int:
        """Get cache TTL in seconds from config or default"""
        return self.config.get("cache_ttl_seconds", self.get_default_cache_ttl())
