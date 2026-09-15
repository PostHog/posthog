"""Stage 2 of the catalog hackathon demo data shim.

Loads the dump directory written by
`products.catalog.backend.scripts.dump_team_for_demo` into a local team.

Usage:

    python manage.py load_catalog_demo_dump \\
        --dump-dir /tmp/catalog-dump \\
        --target-team-id 1

What it does, in order:

  1. Wipes the seven dumped tables for `--target-team-id` (idempotent re-runs).
  2. Loads warehouse tables, then saved queries (so saved-query FKs resolve),
     then joins.
  3. Loads dashboards, then insights, then dashboard tiles (so tile FKs
     resolve).
  4. Loads activity-log rows, remapping `team_id`, `organization_id`,
     `user_id`, and the `item_id` string when it points to a remapped row.

FK strategy:

  - `team_id` is rewritten to the target team.
  - `organization_id` is rewritten to the target team's organization.
  - User FKs (`created_by_id`, `last_modified_by_id`, `user_id`) are nulled.
  - External FKs we cannot resolve (data source, credential, color theme,
    folder, managed viewset, text/button tile) are nulled.
  - UUID-pk rows preserve their prod UUID, which makes intra-dump UUID FK
    resolution automatic. If a referenced UUID was excluded from the dump,
    we null the FK on insert.
  - INT-pk rows get fresh local pks; we keep an old→new map per table and
    rewrite tile / activity-log references.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Model

from posthog.clickhouse.client import sync_execute
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.insight import Insight
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.join import DataWarehouseJoin
from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.event_definitions.backend.models.event_definition import EventDefinition
from products.event_definitions.backend.models.property_definition import PropertyDefinition

# FK columns we never want to carry over — either point to user/org rows we
# don't dump or to other product surfaces (file system, color theme, text /
# button dashboard tiles, taxonomy project) that are out of scope for the
# catalog demo.
USER_FK_COLUMNS = frozenset({"created_by_id", "last_modified_by_id", "user_id"})
ALWAYS_NULL_FKS: dict[str, frozenset[str]] = {
    "DataWarehouseTable": frozenset({"external_data_source_id", "credential_id"}),
    "DataWarehouseSavedQuery": frozenset({"managed_viewset_id", "folder_id"}),
    "Dashboard": frozenset({"data_color_theme_id"}),
    "DashboardTile": frozenset({"text_id", "button_tile_id"}),
    # `project_id` would FK to the prod project row; nulling it keeps the
    # `coalesce(project_id, team_id), name` unique constraint coherent
    # because every dumped row gets rewritten to the same target team_id.
    "EventDefinition": frozenset({"project_id"}),
    "PropertyDefinition": frozenset({"project_id"}),
}

# Columns we INSERT into local `app_metrics2`. Mirrors the SELECT list in
# `dump_team_for_demo._build_app_metrics_sql` and the schema in
# `posthog/models/app_metrics2/sql.py`.
APP_METRICS2_COLUMNS = (
    "team_id",
    "timestamp",
    "app_source",
    "app_source_id",
    "instance_id",
    "metric_kind",
    "metric_name",
    "count",
)

# Scopes in posthog_activitylog whose `item_id` is the pk of a model we
# remapped. We rewrite the string id on insert so the agent can still
# follow the popularity signal back to the local row.
ACTIVITY_LOG_REMAPS: dict[str, str] = {
    "Dashboard": "dashboard",
    "Insight": "insight",
}


class Command(BaseCommand):
    help = "Load a catalog demo dump into a local team."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dump-dir", required=True)
        parser.add_argument("--target-team-id", type=int, required=True)
        parser.add_argument(
            "--keep-existing",
            action="store_true",
            help="Skip the wipe step. Re-runs will likely fail on UUID conflicts unless the prior load was discarded.",
        )
        parser.add_argument(
            "--skip-tables",
            default="",
            help=(
                "Comma-separated list of table names to skip entirely (no wipe, no load). "
                "Names match the dump filenames, e.g. "
                "'posthog_dashboarditem,posthog_propertydefinition,app_metrics2'."
            ),
        )
        parser.add_argument(
            "--default-user-id",
            type=int,
            default=None,
            help=(
                "Local user id to attribute dumped rows to (created_by, last_modified_by, "
                "ActivityLog.user). Defaults to the target team's first OWNER or ADMIN org member."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dump_dir = Path(options["dump_dir"]).resolve()
        target_team_id = options["target_team_id"]

        if not dump_dir.exists():
            raise CommandError(f"dump dir does not exist: {dump_dir}")
        manifest_path = dump_dir / "manifest.json"
        if not manifest_path.exists():
            raise CommandError(f"missing manifest: {manifest_path}")

        manifest = json.loads(manifest_path.read_text())
        source_team_id = manifest["source_team_id"]
        try:
            team = Team.objects.select_related("organization").get(id=target_team_id)
        except Team.DoesNotExist as exc:
            raise CommandError(f"target team {target_team_id} not found") from exc

        self._skip_tables: set[str] = {t.strip() for t in options["skip_tables"].split(",") if t.strip()}
        self._default_user_id: int | None = options["default_user_id"] or self._resolve_default_user_id(team)

        self.stdout.write(
            f"loading dump source_team={source_team_id} region={manifest['region']} "
            f"-> local team_id={target_team_id} ({team.name!r}, org={team.organization_id})"
        )
        if self._default_user_id is not None:
            self.stdout.write(f"attributing dumped rows to user_id={self._default_user_id}")
        else:
            self.stdout.write("no default user resolved; user FKs will be left NULL")
        if self._skip_tables:
            self.stdout.write(f"skipping tables: {sorted(self._skip_tables)}")

        if not options["keep_existing"]:
            self._wipe_target(target_team_id)

        # Per-INT-pk-model maps. Keyed by stringified old pk so we can use
        # them uniformly when rewriting `posthog_activitylog.item_id`, which
        # is itself a string column.
        dashboard_map: dict[str, int] = {}
        insight_map: dict[str, int] = {}
        # Set of UUIDs of warehouse tables we actually loaded — saved-query
        # FKs to anything else need to be nulled to avoid IntegrityError.
        loaded_table_ids: set[str] = set()

        # No outer transaction — `_insert_*_row` is per-row tolerant
        # (logs and continues on errors), and a global atomic would turn
        # one bad row into a load-wide abort via `InFailedSqlTransaction`.
        for row in self._read_rows(dump_dir, "posthog_datawarehousetable"):
            self._insert_uuid_row(
                DataWarehouseTable,
                row,
                target_team_id=target_team_id,
                null_columns=ALWAYS_NULL_FKS["DataWarehouseTable"] | USER_FK_COLUMNS,
            )
            loaded_table_ids.add(row["id"])

        for row in self._read_rows(dump_dir, "posthog_datawarehousesavedquery"):
            # Null table_id if its target wasn't loaded — happens when prod
            # had a saved query pointing at a soft-deleted table.
            if row.get("table_id") and row["table_id"] not in loaded_table_ids:
                row["table_id"] = None
            self._insert_uuid_row(
                DataWarehouseSavedQuery,
                row,
                target_team_id=target_team_id,
                null_columns=ALWAYS_NULL_FKS["DataWarehouseSavedQuery"] | USER_FK_COLUMNS,
            )

        for row in self._read_rows(dump_dir, "posthog_datawarehousejoin"):
            self._insert_uuid_row(
                DataWarehouseJoin,
                row,
                target_team_id=target_team_id,
                null_columns=USER_FK_COLUMNS,
            )

        for row in self._read_rows(dump_dir, "posthog_dashboard"):
            new_id = self._insert_int_row(
                Dashboard,
                row,
                target_team_id=target_team_id,
                null_columns=ALWAYS_NULL_FKS["Dashboard"] | USER_FK_COLUMNS,
            )
            if new_id is not None:
                dashboard_map[str(row["id"])] = new_id

        for row in self._read_rows(dump_dir, "posthog_dashboarditem"):
            # Insight has two Dashboard FKs (legacy `dashboard`, and
            # `dive_dashboard` for drill-down). Both are SET_NULL nullable;
            # remap to local pks where possible, fall through to null.
            for fk_col in ("dashboard_id", "dive_dashboard_id"):
                if row.get(fk_col) is not None:
                    row[fk_col] = dashboard_map.get(str(row[fk_col]))
            new_id = self._insert_int_row(
                Insight,
                row,
                target_team_id=target_team_id,
                null_columns=USER_FK_COLUMNS,
            )
            if new_id is not None:
                insight_map[str(row["id"])] = new_id

        for row in self._read_rows(dump_dir, "posthog_dashboardtile"):
            row["dashboard_id"] = dashboard_map.get(str(row["dashboard_id"]))
            if row["dashboard_id"] is None:
                # Parent dashboard wasn't loaded — skip the orphan tile.
                continue
            # `dash_tile_exactly_one_related_object` requires one of
            # (insight, text, button_tile) to be non-null. We null
            # text_id/button_tile_id unconditionally and only carry
            # insight-bearing tiles forward — text/button tiles aren't
            # something the catalog agent reads.
            if row.get("insight_id") is None:
                continue
            row["insight_id"] = insight_map.get(str(row["insight_id"]))
            if row["insight_id"] is None:
                continue
            self._insert_int_row(
                DashboardTile,
                row,
                target_team_id=None,  # tile has no team_id column
                null_columns=ALWAYS_NULL_FKS["DashboardTile"] | USER_FK_COLUMNS,
            )

        for row in self._read_rows(dump_dir, "posthog_activitylog"):
            self._load_activity_row(row, team, dashboard_map, insight_map)

        for row in self._read_rows(dump_dir, "posthog_eventdefinition"):
            self._insert_uuid_row(
                EventDefinition,
                row,
                target_team_id=target_team_id,
                null_columns=ALWAYS_NULL_FKS["EventDefinition"],
            )

        for row in self._read_rows(dump_dir, "posthog_propertydefinition"):
            self._insert_uuid_row(
                PropertyDefinition,
                row,
                target_team_id=target_team_id,
                null_columns=ALWAYS_NULL_FKS["PropertyDefinition"],
            )

        # ClickHouse insert is outside the Postgres transaction — CH is a
        # separate connection and would not roll back with it anyway.
        self._load_app_metrics2(dump_dir, target_team_id, dashboard_map)

        self.stdout.write(self.style.SUCCESS(f"done: loaded into team_id={target_team_id}"))

    def _wipe_target(self, team_id: int) -> None:
        """Delete existing rows for the target team in the dumped tables.

        Respects `--skip-tables` so a resumed load doesn't blow away rows
        the caller wants to keep.
        """
        self.stdout.write(f"wiping existing rows for team_id={team_id}...")
        wipes: list[tuple[str, Any]] = [
            ("posthog_activitylog", ActivityLog.objects.filter(team_id=team_id)),
            ("posthog_dashboardtile", DashboardTile.objects.filter(dashboard__team_id=team_id)),
            ("posthog_dashboarditem", Insight.objects.filter(team_id=team_id)),
            ("posthog_dashboard", Dashboard.objects.filter(team_id=team_id)),
            ("posthog_datawarehousejoin", DataWarehouseJoin.objects.filter(team_id=team_id)),
            ("posthog_datawarehousesavedquery", DataWarehouseSavedQuery.objects.filter(team_id=team_id)),
            ("posthog_datawarehousetable", DataWarehouseTable.objects.filter(team_id=team_id)),
            ("posthog_eventdefinition", EventDefinition.objects.filter(team_id=team_id)),
            ("posthog_propertydefinition", PropertyDefinition.objects.filter(team_id=team_id)),
        ]
        for table_name, queryset in wipes:
            if table_name in self._skip_tables:
                self.stdout.write(f"  skip wipe {table_name}")
                continue
            queryset.delete()
        # `app_metrics2` is AggregatingMergeTree on ClickHouse — we can't
        # cheaply delete by team_id. Re-loads append rows; the engine
        # de-duplicates on the sort key.

    def _read_rows(self, dump_dir: Path, table: str) -> Iterable[dict[str, Any]]:
        if table in self._skip_tables:
            self.stdout.write(f"skip {table} (--skip-tables)")
            return []
        path = dump_dir / "postgres" / f"{table}.json"
        if not path.exists():
            self.stdout.write(self.style.WARNING(f"  skip {table}: file missing"))
            return []
        rows = json.loads(path.read_text())
        self.stdout.write(f"loading {table}: {len(rows)} rows")
        return rows

    def _resolve_default_user_id(self, team: Team) -> int | None:
        """Pick the team's org owner/admin to attribute dumped rows to.

        Mirrors `_resolve_catalog_task_user` in
        `products/catalog/backend/temporal/activities/agent.py`.
        """
        membership = (
            OrganizationMembership.objects.filter(
                organization_id=team.organization_id,
                level__gte=OrganizationMembership.Level.ADMIN,
            )
            .order_by("-level", "joined_at")
            .first()
        )
        return membership.user_id if membership else None

    def _insert_uuid_row(
        self,
        model: type[Model],
        row: dict[str, Any],
        *,
        target_team_id: int,
        null_columns: frozenset[str],
    ) -> None:
        """Insert a UUID-pk row preserving its UUID.

        Skips rows that already exist in local DB (idempotent within a single
        load; cross-run idempotency comes from the wipe step).
        """
        kwargs = self._build_kwargs(model, row, target_team_id=target_team_id, null_columns=null_columns)
        try:
            model.objects.create(**kwargs)
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"  skipped {model.__name__} id={row.get('id')!r}: {exc}"))

    def _insert_int_row(
        self,
        model: type[Model],
        row: dict[str, Any],
        *,
        target_team_id: int | None,
        null_columns: frozenset[str],
    ) -> int | None:
        """Insert an INT-pk row, letting Postgres assign a new pk.

        Returns the new pk so callers can track old→new mappings, or
        None if the insert failed. Per-row tolerant — logs and continues
        so the load isn't killed by one bad row.
        """
        kwargs = self._build_kwargs(model, row, target_team_id=target_team_id, null_columns=null_columns)
        kwargs.pop("id", None)
        try:
            obj = model.objects.create(**kwargs)
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"  skipped {model.__name__} src_id={row.get('id')!r}: {exc}"))
            return None
        return obj.pk

    def _build_kwargs(
        self,
        model: type[Model],
        row: dict[str, Any],
        *,
        target_team_id: int | None,
        null_columns: frozenset[str],
    ) -> dict[str, Any]:
        """Filter dump dict to model field names and apply standard remaps.

        Also parses JSON-typed columns back into Python objects: Metabase's
        /api/dataset response serializes Postgres JSONB columns as JSON
        strings, but Django's JSONField stores whatever you give it
        verbatim, so passing a string would land an escaped JSON literal
        in the column (the catalog agent would then read e.g. a quoted
        string instead of a `{kind: TrendsQuery, ...}` dict).
        """
        json_columns: set[str] = set()
        attnames: set[str] = set()
        for f in model._meta.get_fields():
            attname = getattr(f, "attname", None)
            if attname is None or f.many_to_many or f.auto_created:
                continue
            attnames.add(attname)
            if getattr(f, "get_internal_type", lambda: "")() == "JSONField":
                json_columns.add(attname)

        kwargs = {k: v for k, v in row.items() if k in attnames}
        for column in json_columns:
            if isinstance(kwargs.get(column), str):
                try:
                    kwargs[column] = json.loads(kwargs[column])
                except json.JSONDecodeError:
                    pass  # leave as-is; the model save will surface the error
        for column in null_columns:
            if column in kwargs:
                kwargs[column] = None
        # Remap user FKs onto a resolved local user so the UI shows
        # "created by <local user>" rather than blank.
        if self._default_user_id is not None:
            for user_fk in USER_FK_COLUMNS:
                if user_fk in attnames:
                    kwargs[user_fk] = self._default_user_id
        if target_team_id is not None and "team_id" in attnames:
            kwargs["team_id"] = target_team_id
        return kwargs

    def _load_activity_row(
        self,
        row: dict[str, Any],
        team: Team,
        dashboard_map: dict[str, int],
        insight_map: dict[str, int],
    ) -> None:
        """ActivityLog has no FK to Team (team_id is a plain int column) and its
        `item_id` is a string pointing at a model pk. Remap both, plus the
        org id and the user FK."""
        kwargs = self._build_kwargs(
            ActivityLog,
            row,
            target_team_id=team.id,
            # `user_id` is in USER_FK_COLUMNS — _build_kwargs will null it
            # or remap to the default user. No extra nulling here.
            null_columns=frozenset(),
        )
        kwargs["organization_id"] = team.organization_id

        scope = kwargs.get("scope")
        item_id_str = str(kwargs.get("item_id")) if kwargs.get("item_id") is not None else None
        if item_id_str and scope in ACTIVITY_LOG_REMAPS:
            mapping = dashboard_map if scope == "Dashboard" else insight_map
            kwargs["item_id"] = str(mapping[item_id_str]) if item_id_str in mapping else None

        kwargs.pop("id", None)  # Let Postgres assign — avoids cross-team UUID reuse confusion.
        try:
            ActivityLog.objects.create(**kwargs)
        except Exception as exc:
            self.stdout.write(
                self.style.WARNING(f"  skipped ActivityLog scope={scope!r} item_id={item_id_str!r}: {exc}")
            )

    def _load_app_metrics2(
        self,
        dump_dir: Path,
        target_team_id: int,
        dashboard_map: dict[str, int],
    ) -> None:
        """Bulk-INSERT the dumped metalytics rows into local `app_metrics2`.

        We INSERT into the distributed table (`app_metrics2`) so ClickHouse
        routes rows to the right shard; the HogQL `app_metrics` virtual
        table reads the same distributed name.

        Two columns get rewritten:

        - `team_id` → target team.
        - `instance_id` → has the form `"<Scope>:<id>"` (see
          `frontend/src/lib/components/Metalytics/metalyticsLogic.ts`).
          For `Dashboard:<int>` rows we remap the int through
          `dashboard_map` so the popularity signal lands on the local
          dashboard rows. `Insight:<short_id>` rows pass through unchanged
          — short_id is preserved by the Postgres load.
        """
        if "app_metrics2" in self._skip_tables:
            self.stdout.write("skip app_metrics2 (--skip-tables)")
            return
        path = dump_dir / "clickhouse" / "app_metrics2.json"
        if not path.exists():
            self.stdout.write(self.style.WARNING("  skip app_metrics2: file missing"))
            return
        rows = json.loads(path.read_text())
        self.stdout.write(f"loading clickhouse/app_metrics2: {len(rows)} rows")
        if not rows:
            return

        tuples: list[tuple[Any, ...]] = []
        for row in rows:
            instance_id = self._remap_metalytics_instance_id(row["instance_id"], dashboard_map)
            if instance_id is None:
                continue  # dashboard pk wasn't loaded; skip orphan view rows
            # Metabase serializes ClickHouse DateTime64 columns as ISO
            # strings. clickhouse_driver's DateTime writer expects datetime
            # instances, so parse before passing.
            timestamp = (
                datetime.fromisoformat(row["timestamp"]) if isinstance(row["timestamp"], str) else row["timestamp"]
            )
            tuples.append(
                (
                    target_team_id,
                    timestamp,
                    row["app_source"],
                    row["app_source_id"],
                    instance_id,
                    row["metric_kind"],
                    row["metric_name"],
                    int(row["count"]),
                )
            )
        if not tuples:
            return
        column_list = ", ".join(APP_METRICS2_COLUMNS)
        sync_execute(f"INSERT INTO app_metrics2 ({column_list}) VALUES", tuples)

    @staticmethod
    def _remap_metalytics_instance_id(instance_id: str, dashboard_map: dict[str, int]) -> str | None:
        """Rewrite a `"<Scope>:<id>"` instance_id so it points at the local row.

        Returns None when the scope is Dashboard and the prod pk isn't in
        our map — the corresponding dashboard was excluded from the dump.
        If `dashboard_map` is empty (caller skipped dashboard load this
        run), passes the instance_id through unchanged rather than dropping
        every Dashboard:<pk> row — the local dashboards may already exist
        from a prior run, and dropping would leave the popularity signal
        empty.
        """
        scope, _, rest = instance_id.partition(":")
        if not rest:
            return instance_id  # no separator — pass through unchanged
        if scope == "Dashboard":
            if not dashboard_map:
                return instance_id  # dashboards not loaded this run; assume local already has them
            new_pk = dashboard_map.get(rest)
            return f"Dashboard:{new_pk}" if new_pk is not None else None
        return instance_id
