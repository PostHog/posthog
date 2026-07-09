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


class DuckgresDailyUsage(UUIDModel):
    """One UTC day of managed-warehouse compute usage for one (team, query_source, worker size).

    Local durable mirror of duckgres's billing pull API (duckgres
    `docs/design/billing-pull-api.md`): a Temporal poller replaces the open
    window's rows on every pull and acks duckgres only at UTC day boundaries,
    so rows here are always complete day-so-far totals. Once duckgres GCs an
    acked day this is the surviving copy until the usage report ships it, so
    it's a system of record, not a scratch buffer. Usage reports (v1 gathers
    and, later, v2 queries) read from this table; nothing else writes to it.
    """

    date = models.DateField()
    organization_id = models.UUIDField()
    # Not an FK: duckgres attributes usage to the org's default team, rows are
    # bulk-replaced every poll, and the billing mirror must survive team deletion.
    team_id = models.IntegerField()
    # "standard" | "endpoints" (open set — duckgres session GUC).
    query_source = models.CharField(max_length=32)
    # Worker size the usage accrued on, as exact decimals (e.g. 8 / 1.5 / 0.5).
    cpu = models.DecimalField(max_digits=12, decimal_places=6)
    mem_gib = models.DecimalField(max_digits=12, decimal_places=6)
    cpu_seconds = models.BigIntegerField()
    memory_seconds = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_duckgresdailyusage"
        verbose_name = "Duckgres daily usage"
        verbose_name_plural = "Duckgres daily usage"
        constraints = [
            models.UniqueConstraint(
                fields=["date", "team_id", "query_source", "cpu", "mem_gib"],
                name="duckgres_daily_usage_key",
            )
        ]


class DuckgresDailyStorageUsage(UUIDModel):
    """One UTC day of managed-warehouse storage usage (footprint integral) per team.

    Sibling of DuckgresDailyUsage for the pull API's `storage` array: one row
    per (org's default team, day), `gib_seconds` = tracked bytes x seconds /
    2^30 as duckgres's exact decimal. Maintained by the same poller
    transaction; read by the storage usage-report gather (which converts to
    decimal-GB hours — GiB vs GB conversion lives there, not here).
    """

    date = models.DateField()
    organization_id = models.UUIDField()
    team_id = models.IntegerField()
    # Up to ~13 integer digits (PB-month scale) + exactly 30 fractional digits.
    gib_seconds = models.DecimalField(max_digits=45, decimal_places=30)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_duckgresdailystorageusage"
        verbose_name = "Duckgres daily storage usage"
        verbose_name_plural = "Duckgres daily storage usage"
        constraints = [
            models.UniqueConstraint(fields=["date", "team_id"], name="duckgres_daily_storage_key"),
        ]


class DuckgresUsageCursor(UUIDModel):
    """Single-row record of the last watermark the poller acked to duckgres.

    Load-bearing: the poller cross-checks this against duckgres's own cursor
    (`watermark_low`) each pull and refuses to ack when duckgres is ahead of it
    (a possible hole in billable usage). Written in the same transaction as the
    mirror rows, before the ack. One row per deployment — `singleton` is a
    unique constant so it's addressable without relying on a magic pk.
    """

    singleton = models.PositiveSmallIntegerField(default=1, unique=True)
    last_acked_watermark = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_duckgresusagecursor"
        verbose_name = "Duckgres usage cursor"
        verbose_name_plural = "Duckgres usage cursors"


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
