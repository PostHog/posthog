"""Backfill data modeling Nodes for saved queries that don't yet have one.

For every non-deleted DataWarehouseSavedQuery without a corresponding Node, attach it
to the team's default DAG and sync its dependency edges. Mirrors what
sync_saved_query_to_dag does when a saved query is created today.

Runs in two passes so that cross-orphan dependencies can resolve:
  Pass 1: create bare Nodes for every orphan
  Pass 2: re-run sync_saved_query_to_dag to parse the query and create edges

Failures are collected into a DLQ printed (and optionally written as JSON) at the
end of the run. Re-run with --saved-query-ids <ids> to retry only those.

Also supports --check-edges: a read-only mode that re-parses each Node's saved
query HogQL and reports drift between expected dependencies and the Node's
existing incoming edges. No mutations.
"""

import json
import time
import logging
from collections import defaultdict
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Exists, OuterRef

import structlog

from products.data_modeling.backend.models import DAG, Edge, Node, NodeType
from products.data_modeling.backend.services.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_warehouse.backend.models import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.modeling import get_parents_from_model_query

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Backfill data modeling Nodes (and edges) for saved queries that don't yet have one"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-ids",
            default=None,
            type=str,
            help="Comma separated list of team IDs to filter by",
        )
        parser.add_argument(
            "--saved-query-ids",
            default=None,
            type=str,
            help=(
                "Comma separated list of saved query IDs to process directly "
                "(bypasses the orphan filter). Use this to retry DLQ entries."
            ),
        )
        parser.add_argument(
            "--batch-size",
            default=50,
            type=int,
            help="Number of saved queries to process per batch (default: 50)",
        )
        parser.add_argument(
            "--batch-delay",
            default=1.0,
            type=float,
            help="Seconds to wait between batches (default: 1.0)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Only show what would be done without making changes",
        )
        parser.add_argument(
            "--dlq-output",
            default=None,
            type=str,
            help="Optional path to write the DLQ (failed saved queries) as JSON",
        )
        parser.add_argument(
            "--check-edges",
            action="store_true",
            default=False,
            help=(
                "Read-only: re-parse each Node's saved query HogQL and report drift "
                "between expected dependencies and existing incoming edges. No writes."
            ),
        )
        parser.add_argument(
            "--check-output",
            default=None,
            type=str,
            help="Optional path to write the check-edges drift report as JSON",
        )
        parser.add_argument(
            "--start-after-saved-query-id",
            default=None,
            type=str,
            help=(
                "Resume cursor: skip every saved query whose id is <= this UUID. "
                "Each batch logs the cursor it just finished so an interrupted run can be resumed."
            ),
        )

    def handle(self, **options):
        logger.setLevel(logging.INFO)

        if options.get("check_edges"):
            self._handle_check(options)
            return

        targets = self._load_targets(options)
        total = len(targets)
        if total == 0:
            logger.info("No saved queries to process, nothing to do")
            return
        logger.info(f"Found {total} saved queries to process")

        if options["dry_run"]:
            for sq in targets:
                logger.info(
                    "Would backfill Node + edges",
                    saved_query_id=str(sq.id),
                    team_id=sq.team_id,
                    name=sq.name,
                )
            logger.info(f"Dry run complete. Would process {total} saved queries")
            return

        if not settings.TEST:
            confirm = input(f"\n\tWill backfill Nodes for {total} saved queries. Proceed? (y/n) ")
            if confirm.strip().lower() != "y":
                logger.info("Aborting")
                return

        batch_size = options["batch_size"]
        batch_delay = options["batch_delay"]
        # keyed by str(saved_query_id); pass-2 success deletes the entry, pass-2 failure
        # overwrites. Whatever remains at the end is the DLQ.
        failures: dict[str, dict] = {}

        logger.info("Pass 1/2: creating bare Nodes")
        pass1_ok = self._run_pass(
            targets,
            batch_size,
            batch_delay,
            self._create_bare_node,
            pass_label="pass1",
            failures=failures,
        )
        logger.info(f"Pass 1 complete: ok={pass1_ok}, failed={total - pass1_ok}")

        logger.info("Pass 2/2: syncing edges")
        pass2_ok = self._run_pass(
            targets,
            batch_size,
            batch_delay,
            self._sync_edges,
            pass_label="pass2",
            failures=failures,
        )
        logger.info(f"Pass 2 complete: ok={pass2_ok}, failed={total - pass2_ok}")

        logger.info(
            "Done!",
            total=total,
            pass1_ok=pass1_ok,
            pass2_ok=pass2_ok,
            dlq_size=len(failures),
        )

        self._report_dlq(failures, options.get("dlq_output"))

    def _load_targets(self, options) -> list[DataWarehouseSavedQuery]:
        cursor = self._parse_cursor(options)
        if options.get("saved_query_ids") is not None:
            try:
                ids = [UUID(s.strip()) for s in options["saved_query_ids"].split(",") if s.strip()]
            except ValueError as e:
                raise CommandError(f"--saved-query-ids must be comma-separated UUIDs: {e}")
            qs = (
                DataWarehouseSavedQuery.objects.exclude(deleted=True)
                .filter(id__in=ids)
                .select_related("team")
                .order_by("id")
            )
            if cursor is not None:
                qs = qs.filter(id__gt=cursor)
            targets = list(qs)
            found_ids = {sq.id for sq in targets}
            missing = [str(uid) for uid in ids if uid not in found_ids and (cursor is None or uid > cursor)]
            if missing:
                logger.warning("Some saved query IDs were not found or are deleted", missing=missing)
            return targets

        qs = (
            DataWarehouseSavedQuery.objects.exclude(deleted=True)
            .annotate(has_node=Exists(Node.objects.filter(saved_query_id=OuterRef("id"))))
            .filter(has_node=False)
            .select_related("team")
            .order_by("id")
        )
        if options.get("team_ids") is not None:
            try:
                team_ids = [int(tid) for tid in options["team_ids"].split(",")]
            except ValueError:
                raise CommandError("--team-ids must be a comma separated list of team IDs")
            qs = qs.filter(team_id__in=team_ids)
        if cursor is not None:
            qs = qs.filter(id__gt=cursor)
        return list(qs)

    def _parse_cursor(self, options) -> UUID | None:
        raw = options.get("start_after_saved_query_id")
        if raw is None:
            return None
        try:
            return UUID(raw)
        except ValueError as e:
            raise CommandError(f"--start-after-saved-query-id must be a UUID: {e}")

    def _run_pass(self, targets, batch_size, batch_delay, fn, *, pass_label, failures) -> int:
        total = len(targets)
        ok = 0
        total_batches = (total + batch_size - 1) // batch_size
        for batch_start in range(0, total, batch_size):
            batch_num = batch_start // batch_size + 1
            batch = targets[batch_start : batch_start + batch_size]
            logger.info(f"{pass_label}: batch {batch_num}/{total_batches} ({len(batch)} queries)")
            last_id = None
            for sq in batch:
                sq_id = str(sq.id)
                try:
                    fn(sq)
                    ok += 1
                    # pass-2 success clears any earlier failure for this saved query
                    failures.pop(sq_id, None)
                except Exception as exc:
                    failures[sq_id] = {
                        "saved_query_id": sq_id,
                        "team_id": sq.team_id,
                        "name": sq.name,
                        "pass": pass_label,
                        "error_class": type(exc).__name__,
                        "error_message": str(exc),
                    }
                    logger.exception(
                        f"{pass_label} failed",
                        saved_query_id=sq_id,
                        team_id=sq.team_id,
                        name=sq.name,
                    )
                last_id = sq_id
            if last_id is not None:
                logger.info(
                    f"{pass_label}: batch {batch_num} complete — resume with --start-after-saved-query-id {last_id}",
                    pass_label=pass_label,
                    batch_num=batch_num,
                    cursor=last_id,
                )
            if batch_start + batch_size < total:
                time.sleep(batch_delay)
        return ok

    def _create_bare_node(self, sq: DataWarehouseSavedQuery) -> None:
        dag = DAG.get_or_create_default(sq.team)
        Node.objects.get_or_create(
            team=sq.team,
            saved_query=sq,
            dag=dag,
            defaults={"name": sq.name, "type": _initial_node_type(sq), "properties": {}},
        )

    def _sync_edges(self, sq: DataWarehouseSavedQuery) -> None:
        sync_saved_query_to_dag(sq)

    def _handle_check(self, options) -> None:
        nodes_with_edges = self._load_check_targets(options)
        total = len(nodes_with_edges)
        if total == 0:
            logger.info("No Noded saved queries to check, nothing to do")
            return
        logger.info(f"Checking edge drift for {total} Nodes")

        batch_size = options["batch_size"]
        batch_delay = options["batch_delay"]
        drift: list[dict] = []
        parse_errors: list[dict] = []
        ok = 0

        total_batches = (total + batch_size - 1) // batch_size
        for batch_start in range(0, total, batch_size):
            batch_num = batch_start // batch_size + 1
            batch = nodes_with_edges[batch_start : batch_start + batch_size]
            logger.info(f"check: batch {batch_num}/{total_batches} ({len(batch)} nodes)")
            last_id = None
            for node, sq, actual_dep_names in batch:
                result = self._check_one(node, sq, actual_dep_names)
                if result["status"] == "ok":
                    ok += 1
                elif result["status"] == "drift":
                    drift.append(result)
                else:
                    parse_errors.append(result)
                last_id = str(sq.id)
            if last_id is not None:
                logger.info(
                    f"check: batch {batch_num} complete — resume with --start-after-saved-query-id {last_id}",
                    batch_num=batch_num,
                    cursor=last_id,
                )
            if batch_start + batch_size < total:
                time.sleep(batch_delay)

        # by_kind breakdown gives a quick triage signal: are we mostly missing deps,
        # extra deps, or unparseable queries?
        by_kind: dict[str, int] = defaultdict(int)
        for entry in drift:
            if entry["missing"] and entry["extra"]:
                by_kind["missing_and_extra"] += 1
            elif entry["missing"]:
                by_kind["missing_only"] += 1
            else:
                by_kind["extra_only"] += 1
        by_parse_error: dict[str, int] = defaultdict(int)
        for entry in parse_errors:
            by_parse_error[entry["error_class"]] += 1

        logger.info(
            "Check complete",
            total=total,
            ok=ok,
            drift=len(drift),
            drift_by_kind=dict(by_kind),
            parse_errors=len(parse_errors),
            parse_errors_by_class=dict(by_parse_error),
        )
        self._report_check(drift, parse_errors, options.get("check_output"))

    def _load_check_targets(self, options) -> list[tuple[Node, DataWarehouseSavedQuery, list[str]]]:
        cursor = self._parse_cursor(options)
        nodes_qs = (
            Node.objects.filter(saved_query__isnull=False)
            .exclude(saved_query__deleted=True)
            .select_related("team", "saved_query")
            .order_by("saved_query_id")
        )
        if options.get("saved_query_ids") is not None:
            try:
                ids = [UUID(s.strip()) for s in options["saved_query_ids"].split(",") if s.strip()]
            except ValueError as e:
                raise CommandError(f"--saved-query-ids must be comma-separated UUIDs: {e}")
            nodes_qs = nodes_qs.filter(saved_query_id__in=ids)
        elif options.get("team_ids") is not None:
            try:
                team_ids = [int(tid) for tid in options["team_ids"].split(",")]
            except ValueError:
                raise CommandError("--team-ids must be a comma separated list of team IDs")
            nodes_qs = nodes_qs.filter(team_id__in=team_ids)
        if cursor is not None:
            nodes_qs = nodes_qs.filter(saved_query_id__gt=cursor)

        nodes = list(nodes_qs)
        if not nodes:
            return []

        # batch-fetch all edges once so we don't N+1 across thousands of nodes
        edges = Edge.objects.filter(target_id__in=[n.id for n in nodes]).values_list("target_id", "source__name")
        edges_by_target: dict[UUID, list[str]] = defaultdict(list)
        for target_id, source_name in edges:
            edges_by_target[target_id].append(source_name)

        return [(n, n.saved_query, edges_by_target.get(n.id, [])) for n in nodes]

    def _check_one(self, node: Node, sq: DataWarehouseSavedQuery, actual_dep_names: list[str]) -> dict:
        base = {"saved_query_id": str(sq.id), "team_id": sq.team_id, "name": sq.name, "node_id": str(node.id)}
        model_query = sq.query.get("query") if sq.query else None
        if not model_query:
            return {
                **base,
                "status": "parse_error",
                "error_class": "MissingQuery",
                "error_message": "saved_query.query.query is empty",
            }
        try:
            expected_set = get_parents_from_model_query(sq.team, sq.name, model_query)
        except Exception as exc:
            logger.exception("check parse failed", saved_query_id=str(sq.id), team_id=sq.team_id, name=sq.name)
            return {**base, "status": "parse_error", "error_class": type(exc).__name__, "error_message": str(exc)}
        expected = sorted(expected_set)
        actual = sorted(set(actual_dep_names))
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        if missing or extra:
            return {
                **base,
                "status": "drift",
                "expected_deps": expected,
                "actual_deps": actual,
                "missing": missing,
                "extra": extra,
            }
        return {**base, "status": "ok"}

    def _report_check(self, drift: list[dict], parse_errors: list[dict], check_output: str | None) -> None:
        if not drift and not parse_errors:
            logger.info("No drift detected — every Node's edges match its current saved query")
            return
        if drift:
            drift_ids_csv = ",".join(entry["saved_query_id"] for entry in drift)
            self.stdout.write("\nDrifted saved query IDs (resync candidates):")
            self.stdout.write(drift_ids_csv)
        if parse_errors:
            err_ids_csv = ",".join(entry["saved_query_id"] for entry in parse_errors)
            self.stdout.write("\nUnparseable saved query IDs (need manual review):")
            self.stdout.write(err_ids_csv)
        if check_output:
            path = Path(check_output)
            path.write_text(json.dumps({"drift": drift, "parse_errors": parse_errors}, indent=2, sort_keys=True))
            logger.info("Wrote check report", path=str(path), drift=len(drift), parse_errors=len(parse_errors))

    def _report_dlq(self, failures: dict[str, dict], dlq_output: str | None) -> None:
        if not failures:
            logger.info("DLQ is empty — all saved queries successfully backfilled")
            return
        entries = list(failures.values())
        ids_csv = ",".join(entry["saved_query_id"] for entry in entries)
        # break down by error class for quick triage
        by_error: dict[str, int] = {}
        for entry in entries:
            by_error[entry["error_class"]] = by_error.get(entry["error_class"], 0) + 1
        logger.warning(
            "DLQ summary",
            dlq_size=len(entries),
            by_error_class=by_error,
        )
        # printed directly so the user can copy-paste into --saved-query-ids without
        # parsing structured logs
        self.stdout.write("\nFailed saved query IDs (retry with --saved-query-ids):")
        self.stdout.write(ids_csv)
        if dlq_output:
            path = Path(dlq_output)
            path.write_text(json.dumps(entries, indent=2, sort_keys=True))
            logger.info("Wrote DLQ to file", path=str(path), entries=len(entries))


def _initial_node_type(sq: DataWarehouseSavedQuery) -> NodeType:
    if sq.origin == DataWarehouseSavedQuery.Origin.ENDPOINT:
        return NodeType.ENDPOINT
    if sq.table_id is not None:
        return NodeType.MAT_VIEW
    return NodeType.VIEW
