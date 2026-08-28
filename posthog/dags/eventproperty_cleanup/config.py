import dagster
from pydantic import Field


class EventPropertyCleanupConfig(dagster.Config):
    """Run-time knobs for the posthog_eventproperty cleanup job. Every default is the safe choice."""

    # Safety
    dry_run: bool = Field(
        default=True,
        description="Discover and score only. No DELETE or VACUUM is issued.",
    )
    require_primary: bool = Field(
        default=True,
        description="Fail preflight unless the Django default connection is a writable primary.",
    )
    require_discovery_replica: bool = Field(
        default=False,
        description=(
            "Fail preflight when no read replica connection is configured. When false, discovery and "
            "scoring read the primary with a warning. Deletes always run on the primary."
        ),
    )
    require_no_replication_slots: bool = Field(
        default=True,
        description=(
            "Fail preflight if pg_replication_slots is non-empty. "
            "An inactive logical slot would retain all WAL this job generates."
        ),
    )
    max_rows: int | None = Field(
        default=None,
        description="Stop a unit once this many rows were deleted in the run.",
    )
    max_runtime_minutes: int | None = Field(
        default=None,
        description="Stop starting new batches after this many minutes.",
    )
    never_delete_team_ids: list[int] = Field(
        default_factory=list,
        description="Teams that are never touched by any mode.",
    )

    # Pacing
    discovery_team_chunk: int = Field(
        default=5_000,
        gt=0,
        description="Team ids per discovery statement. Discovery walks team_id ranges instead of scanning whole tables.",
    )
    discovery_sleep_seconds: float = Field(default=0.2, ge=0, description="Sleep between discovery statements.")
    batch_size: int = Field(default=30_000, gt=0, description="Rows per DELETE statement.")
    sleep_seconds: float = Field(default=0.5, ge=0, description="Sleep between batches.")
    lock_timeout: str = Field(default="2s", description="Postgres lock_timeout per DELETE.")
    statement_timeout: str = Field(default="60s", description="Postgres statement_timeout per DELETE.")
    pause_dead_tuple_ratio: float = Field(
        default=0.02,
        description="Pause while n_dead_tup / n_live_tup on posthog_eventproperty is above this.",
    )
    pause_propdefs_blocked_backends: int = Field(
        default=8,
        description="Pause while at least this many property-defs-rs backends wait on Lock or IO.",
    )
    pause_seconds: float = Field(default=30.0, ge=0, description="Sleep per pause before re-probing health.")
    health_probe_interval_seconds: float = Field(default=10.0, ge=0, description="Minimum time between health probes.")
    require_activity_visibility: bool = Field(
        default=False,
        description=(
            "Fail preflight when the database role cannot see other sessions' wait events "
            "(pg_read_all_stats). When false the blocked-propdefs pause signal is disabled with a warning."
        ),
    )
    revalidate_every_batches: int = Field(
        default=50,
        gt=0,
        description="Re-check a unit's eligibility every N batches and stop the unit if it no longer qualifies.",
    )

    # Vacuum
    vacuum: bool = Field(default=True, description="Run explicit VACUUM (INDEX_CLEANUP ON) during the run.")
    rows_between_vacuum: int = Field(
        default=150_000_000,
        gt=0,
        description="Rows deleted before an explicit VACUUM. Keep under ~179M, the PG15 one-pass dead-TID limit.",
    )
    vacuum_on_start: bool = Field(default=True, description="VACUUM once in preflight so a resumed run starts clean.")
    vacuum_cost_delay_ms: int = Field(default=2, ge=0, description="vacuum_cost_delay for the explicit VACUUM session.")
    vacuum_cost_limit: int = Field(default=200, gt=0, description="vacuum_cost_limit for the explicit VACUUM session.")

    # Mode 2a: pollution
    pollution_enabled: bool = Field(
        default=True,
        description="Delete rows whose property has no EVENT-type definition in the project.",
    )
    team_ids: list[int] | None = Field(
        default=None,
        description="Restrict pollution and retention modes to these teams. None means every team with candidates.",
    )
    skip_paying_orgs: bool = Field(
        default=True,
        description="Skip teams whose organization has an active subscription.",
    )

    # Mode 2b: event-level retention
    retention_days: int | None = Field(
        default=None,
        description="Delete rows for events last seen more than this many days ago. None disables the mode.",
    )
    retention_event_batch: int = Field(default=200, gt=0, description="Event names per retention DELETE.")

    # Mode 2c: dormant tenants
    dormant_discovery_enabled: bool = Field(
        default=False,
        description="Score the largest tenants for dormancy and report the scorecard.",
    )
    dormant_days: int = Field(default=180, gt=0, description="Every dormancy signal must be older than this.")
    dormant_top_n: int = Field(
        default=25,
        gt=0,
        le=100,
        description=(
            "Score at most this many tenants, largest first. Candidates come from the planner's "
            "most-common-values list for team_id, which holds at most 100 entries."
        ),
    )
    dormant_approved_team_ids: list[int] = Field(
        default_factory=list,
        description="Dormant tenants to delete. A team is deleted only if it is in this list AND passes every signal now.",
    )
    dormant_persons_probe_timeout: str = Field(
        default="5s",
        description="statement_timeout for the persons DB probe. A timeout marks the tenant not eligible.",
    )
