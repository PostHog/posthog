from __future__ import annotations

from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class DuckgresServer(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """Per-organization duckgres query server + DuckLake catalog connection details.

    Duckgres is a Postgres-protocol-compatible DuckDB server. Each org that uses
    duckgres for copy workflows/backfills needs its own connection entry. The
    DuckLake catalog is a *separate* Postgres metadata store (the duckgres server's
    query connection is not the same endpoint), so its connection is recorded here
    too under the ``catalog_*`` fields.
    """

    organization = models.OneToOneField(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="duckgres_server",
    )

    # Duckgres query-server connection.
    host = models.CharField(max_length=255)
    port = models.IntegerField(default=5432)
    flight_port = models.IntegerField(default=8815)
    database = models.CharField(max_length=255, default="ducklake")
    username = models.CharField(max_length=255)
    password = EncryptedTextField(max_length=500)

    # DuckLake catalog Postgres connection — a separate metadata store from the
    # query server above. Nullable: an org may have a provisioned server before its
    # catalog row is recorded (the dev/env-var path doesn't need these at all).
    catalog_host = models.CharField(max_length=255, null=True, blank=True)
    catalog_port = models.IntegerField(default=5432)
    catalog_database = models.CharField(max_length=255, default="ducklake")
    catalog_username = models.CharField(max_length=255, null=True, blank=True)
    catalog_password = EncryptedTextField(max_length=500, null=True, blank=True)

    # S3 bucket backing the org's managed warehouse (no secrets — access is via IRSA / the
    # ClickHouse EC2 role). Written at provision time so the duckling backfill reads the
    # authoritative bucket name instead of re-deriving it. Nullable for rows provisioned
    # before this field existed.
    bucket = models.CharField(max_length=255, null=True, blank=True)
    # Region travels with the bucket: set alongside it, left NULL when no bucket is
    # recorded yet (status_for()'s self-heal fills both in once the control plane reports them).
    bucket_region = models.CharField(max_length=50, null=True, blank=True, default=None)

    class Meta:
        db_table = "posthog_duckgresserver"
        verbose_name = "Duckgres server"
        verbose_name_plural = "Duckgres servers"

    def to_catalog_public_config(self) -> dict[str, str]:
        """DuckLake catalog config without secrets (safe for logging/debugging)."""
        return {
            "DUCKLAKE_RDS_HOST": self.catalog_host or "",
            "DUCKLAKE_RDS_PORT": str(self.catalog_port),
            "DUCKLAKE_RDS_DATABASE": self.catalog_database,
            "DUCKLAKE_RDS_USERNAME": self.catalog_username or "",
            "DUCKLAKE_BUCKET": self.bucket or "",
            "DUCKLAKE_BUCKET_REGION": self.bucket_region or "",
            "DUCKLAKE_S3_ACCESS_KEY": "",
            "DUCKLAKE_S3_SECRET_KEY": "",
        }


class DuckgresServerTeam(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """Per-team membership of an org's Duckgres warehouse + that team's backfill state.

    A DuckgresServer is org-scoped and can host many teams (1->n). This model records
    which teams live in a given server and carries the team-specific warehouse backfill
    configuration (whether backfills are enabled, the per-team table suffix, and the
    cached backfill floor).
    """

    server = models.ForeignKey(
        "posthog.DuckgresServer",
        on_delete=models.CASCADE,
        related_name="teams",
    )
    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="duckgres_server_team",
    )
    backfill_enabled = models.BooleanField(
        default=True,
        help_text="Whether warehouse backfills are enabled for this team",
    )
    table_suffix = models.CharField(
        max_length=63,
        null=True,
        blank=True,
        help_text="Suffix for this team's warehouse tables in the duckling (events_<suffix>, persons_<suffix>). "
        "User-supplied; falls back to the shared tables when unset.",
    )
    earliest_event_date = models.DateField(
        null=True,
        blank=True,
        help_text="Cached earliest event date (clamped to the backfill floor) used to size the historical "
        "backfill range. Populated lazily by the full-backfill sensor so it never re-queries ClickHouse; "
        "leave unset to have the sensor resolve and store it on its next tick.",
    )

    class Meta:
        db_table = "posthog_duckgresserverteam"
        verbose_name = "Duckgres server team"
        verbose_name_plural = "Duckgres server teams"


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

    # db_constraint=False: a real FK constraint on posthog_team locks that hot
    # table when this table is created (HotTableAlterPolicy). The tenant link is
    # enforced at the app level.
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="duckgres_sink_schema_states",
        db_constraint=False,
    )
    # ExternalDataSchema id. Not a FK: the queue addresses schemas by string id
    # and the schema row may be soft-deleted while sink state must survive for
    # cleanup decisions.
    schema_id = models.UUIDField(unique=True)
    state = models.CharField(max_length=32, choices=State.choices, default=State.PENDING_BACKFILL)
    # Delta table version the backfill is pinned to.
    snapshot_version = models.BigIntegerField(null=True, blank=True)
    # Deprecated planning boundary retained for rows created by older planner
    # revisions. New plans derive containment from Delta commit versions.
    plan_cutoff = models.DateTimeField(null=True, blank=True)
    backfill_run_uuid = models.CharField(max_length=200, null=True, blank=True)
    chunk_count = models.IntegerField(null=True, blank=True)
    chunks_applied = models.IntegerField(default=0)
    last_error = models.TextField(null=True, blank=True)
    # Override CreatedMetaFields.created_by to drop the DB-level FK: a real
    # constraint on posthog_user takes a lock on that hot table when this table
    # is created (HotTableAlterPolicy). App-level enforcement is enough for an
    # optional audit pointer.
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
    )

    class Meta:
        db_table = "posthog_duckgressinkschemastate"
        verbose_name = "Duckgres sink schema state"
        verbose_name_plural = "Duckgres sink schema states"
        indexes = [models.Index(fields=["team", "state"], name="duckgres_sink_team_state_idx")]
