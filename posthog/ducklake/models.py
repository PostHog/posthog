from __future__ import annotations

from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class DuckLakeCatalog(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """Per-organization DuckLake catalog configuration.

    Stores database connection details and bucket configuration for orgs that need
    isolated DuckLake catalogs (e.g., managed warehouse customers).

    For orgs without a DuckLakeCatalog entry, the system falls back to
    environment variable configuration.
    """

    # Deprecated: use organization instead. Kept nullable for backward compatibility.
    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="ducklake_catalog",
        null=True,
        blank=True,
    )
    organization = models.OneToOneField(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="ducklake_catalog",
    )

    # Database connection settings
    db_host = models.CharField(max_length=255)
    db_port = models.IntegerField(default=5432)
    db_database = models.CharField(max_length=255, default="ducklake")
    db_username = models.CharField(max_length=255)
    db_password = EncryptedTextField(max_length=500)

    # Bucket settings (no secrets - credentials come from IRSA or storage.py)
    bucket = models.CharField(max_length=255)
    bucket_region = models.CharField(max_length=50, default="us-east-1")

    class Meta:
        db_table = "posthog_ducklakecatalog"
        verbose_name = "DuckLake catalog"
        verbose_name_plural = "DuckLake catalogs"

    def to_public_config(self) -> dict[str, str]:
        """Convert to a config dict without secrets (safe for logging/debugging)."""
        return {
            "DUCKLAKE_RDS_HOST": self.db_host,
            "DUCKLAKE_RDS_PORT": str(self.db_port),
            "DUCKLAKE_RDS_DATABASE": self.db_database,
            "DUCKLAKE_RDS_USERNAME": self.db_username,
            "DUCKLAKE_BUCKET": self.bucket,
            "DUCKLAKE_BUCKET_REGION": self.bucket_region,
            "DUCKLAKE_S3_ACCESS_KEY": "",
            "DUCKLAKE_S3_SECRET_KEY": "",
        }


class DuckgresServer(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """Per-organization duckgres query server connection details.

    Duckgres is a Postgres-protocol-compatible DuckDB server, separate from
    the DuckLake catalog Postgres database. Each org that uses duckgres for
    copy workflows needs its own connection entry.
    """

    # Deprecated: use organization instead. Kept nullable for backward compatibility.
    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="duckgres_server",
        null=True,
        blank=True,
    )
    organization = models.OneToOneField(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="duckgres_server",
    )
    host = models.CharField(max_length=255)
    port = models.IntegerField(default=5432)
    flight_port = models.IntegerField(default=8815)
    database = models.CharField(max_length=255, default="ducklake")
    username = models.CharField(max_length=255)
    password = EncryptedTextField(max_length=500)

    # S3 bucket backing the org's managed warehouse (no secrets — access is via IRSA / the
    # ClickHouse EC2 role). Written at provision time so the duckling backfill reads the
    # authoritative bucket name instead of re-deriving it. Nullable for rows provisioned
    # before this field existed.
    bucket = models.CharField(max_length=255, null=True, blank=True)
    bucket_region = models.CharField(max_length=50, default="us-east-1")

    class Meta:
        db_table = "posthog_duckgresserver"
        verbose_name = "Duckgres server"
        verbose_name_plural = "Duckgres servers"


class DuckLakeBackfill(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """Per-team enablement of DuckLake warehouse backfills.

    Controls which teams should be backfilled by the Dagster duckling sensors.
    Catalog credentials are resolved from the team's organization via
    DuckLakeCatalog/DuckgresServer — this model only tracks enablement.
    """

    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="ducklake_backfill",
    )
    enabled = models.BooleanField(
        default=True,
        help_text="Whether warehouse backfills are enabled for this team",
    )

    class Meta:
        db_table = "posthog_ducklakebackfill"
        verbose_name = "DuckLake backfill"
        verbose_name_plural = "DuckLake backfills"


class DuckgresSinkSchemaState(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    r"""Per-schema lifecycle of the Duckgres v3 batch sink.

    The sink only applies live batches for a schema once its history has been
    primed into duckgres (or it needs no priming). The backfill planner owns
    the transitions:

    PENDING_BACKFILL -> BACKFILLING -> PRIMED
                              \-> (superseded by a live full refresh) -> PRIMED
    PRIMED -> NEEDS_RESYNC (retention-loss gap) -> PENDING_BACKFILL
    """

    class State(models.TextChoices):
        PENDING_BACKFILL = "pending_backfill", "Pending backfill"
        BACKFILLING = "backfilling", "Backfilling"
        PRIMED = "primed", "Primed"
        NEEDS_RESYNC = "needs_resync", "Needs resync"

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="duckgres_sink_schema_states",
    )
    # ExternalDataSchema id. Not a FK: the queue addresses schemas by string id
    # and the schema row may be soft-deleted while sink state must survive for
    # cleanup decisions.
    schema_id = models.UUIDField(unique=True)
    state = models.CharField(max_length=32, choices=State.choices, default=State.PENDING_BACKFILL)
    # Delta table version the backfill is pinned to.
    snapshot_version = models.BigIntegerField(null=True, blank=True)
    # Queue-DB clock taken BEFORE the snapshot was resolved: only runs whose
    # every batch was delta-succeeded by this instant are provably contained
    # in the snapshot and safe to retire.
    plan_cutoff = models.DateTimeField(null=True, blank=True)
    backfill_run_uuid = models.CharField(max_length=200, null=True, blank=True)
    chunk_count = models.IntegerField(null=True, blank=True)
    chunks_applied = models.IntegerField(default=0)
    last_error = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "posthog_duckgressinkschemastate"
        verbose_name = "Duckgres sink schema state"
        verbose_name_plural = "Duckgres sink schema states"
        indexes = [models.Index(fields=["team", "state"], name="duckgres_sink_team_state_idx")]
