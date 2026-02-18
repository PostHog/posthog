from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.migrations.loader import MigrationLoader

from posthog.management.migration_squashing.planner import MigrationSquashPlanner, OperationBlocker, SquashAnalysis
from posthog.management.migration_squashing.policy import BootstrapPolicy, write_bootstrap_policy_template

REVIEW_GUIDELINES_PATH = "posthog/management/migration_squashing/REVIEW_GUIDELINES.md"


@dataclass
class PlannedChunk:
    analysis: SquashAnalysis
    state_split_from_end: str | None = None


@dataclass
class IncrementalPlan:
    app_label: str
    start: str
    end: str
    min_chunk_size: int
    rewrite_concurrent_indexes: bool
    bootstrap_policy_path: str | None
    scope: list[str]
    chunks: list[PlannedChunk]
    blockers: list[OperationBlocker]
    blocked_migrations: list[str]
    uncovered_migrations: list[str]
    total_operations: int
    chunk_operations: int
    blocked_operations: int

    @property
    def covered_count(self) -> int:
        covered = set(self.blocked_migrations)
        for chunk in self.chunks:
            covered.update(chunk.analysis.included_span)
        return len(covered)


class Command(BaseCommand):
    help = "Build a full incremental squash plan and optionally write all chunk migrations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--app",
            default="posthog",
            help="Django app label to squash (defaults to posthog).",
        )
        parser.add_argument(
            "--start",
            help="Inclusive start migration name. Defaults to first migration after latest existing squash.",
        )
        parser.add_argument(
            "--end",
            help="Inclusive end migration name. Defaults to max_migration.txt (or latest non-squashed migration).",
        )
        parser.add_argument(
            "--allow-operation",
            action="append",
            default=[],
            help="Operation type to allow despite default safety blocklist. Can be passed multiple times.",
        )
        parser.add_argument(
            "--min-chunk-size",
            type=int,
            default=2,
            help="Minimum number of migrations per squash chunk. Defaults to 2 to avoid singleton squashes.",
        )
        parser.add_argument(
            "--rewrite-concurrent-indexes",
            action="store_true",
            help=(
                "Rewrite index-concurrent operations to bootstrap-safe non-concurrent variants "
                "when writing squashed migrations."
            ),
        )
        parser.add_argument(
            "--bootstrap-policy",
            help=(
                "Optional YAML policy file for resolving blocked operations. "
                "Unresolved entries (missing action) remain blockers."
            ),
        )
        parser.add_argument(
            "--bootstrap-policy-template",
            help=(
                "Optional path to write/update a policy template YAML with blocker operation identities. "
                "Existing actions are preserved. "
                f"Review entries using {REVIEW_GUIDELINES_PATH}."
            ),
        )
        parser.add_argument(
            "--json-report",
            help="Optional path to write the full plan report as JSON.",
        )
        parser.add_argument(
            "--markdown-report",
            help="Optional path to write a reviewer-friendly markdown report.",
        )
        parser.add_argument(
            "--commands-report",
            help="Optional path to write rerunnable `build_migration_squash` commands for all chunks.",
        )
        parser.add_argument(
            "--write",
            action="store_true",
            help="Write all planned squash migration chunks.",
        )

    def handle(self, *args, **options):
        app_label: str = options["app"]
        allow_operation_types = set(options["allow_operation"])
        min_chunk_size: int = options["min_chunk_size"]
        rewrite_concurrent_indexes: bool = options["rewrite_concurrent_indexes"]
        bootstrap_policy_arg: str | None = options.get("bootstrap_policy")
        bootstrap_policy_path = Path(bootstrap_policy_arg) if bootstrap_policy_arg else None
        bootstrap_policy = BootstrapPolicy.from_path(bootstrap_policy_path)
        if min_chunk_size < 1:
            raise CommandError("--min-chunk-size must be at least 1.")

        loader = MigrationLoader(None, ignore_no_migrations=True)
        planner = MigrationSquashPlanner(
            loader=loader,
            app_label=app_label,
            allow_operation_types=allow_operation_types,
            bootstrap_policy=bootstrap_policy,
        )

        start_name = options["start"] or planner.infer_default_start()
        end_name = options["end"] or planner.infer_default_end()

        plan = self._build_incremental_plan(
            planner=planner,
            start_name=start_name,
            end_name=end_name,
            min_chunk_size=min_chunk_size,
            rewrite_concurrent_indexes=rewrite_concurrent_indexes,
            bootstrap_policy_path=str(bootstrap_policy_path) if bootstrap_policy_path else None,
        )
        self._print_summary(plan)

        json_report = options.get("json_report")
        if json_report:
            report_path = Path(json_report)
            report_path.write_text(json.dumps(self._plan_to_json(plan), indent=2, sort_keys=True) + "\n")
            self.stdout.write(f"Wrote JSON report to {report_path}")

        markdown_report = options.get("markdown_report")
        if markdown_report:
            report_path = Path(markdown_report)
            report_path.write_text(self._plan_to_markdown(plan))
            self.stdout.write(f"Wrote markdown report to {report_path}")

        commands_report = options.get("commands_report")
        if commands_report:
            report_path = Path(commands_report)
            report_path.write_text(
                self._plan_to_commands(
                    plan=plan,
                    app_label=app_label,
                    bootstrap_policy_path=bootstrap_policy_path,
                )
            )
            self.stdout.write(f"Wrote commands report to {report_path}")

        bootstrap_policy_template = options.get("bootstrap_policy_template")
        if bootstrap_policy_template:
            template_path = Path(bootstrap_policy_template)
            write_bootstrap_policy_template(
                path=template_path,
                app_label=app_label,
                blockers=plan.blockers,
            )
            self.stdout.write(f"Wrote bootstrap policy template to {template_path}")
            self.stdout.write(f"Review guide: {REVIEW_GUIDELINES_PATH}")

        if plan.uncovered_migrations:
            raise CommandError("Plan left uncovered migrations. Refusing to continue.")

        if plan.chunk_operations + plan.blocked_operations != plan.total_operations:
            raise CommandError("Operation coverage mismatch detected. Refusing to continue.")

        if options["write"]:
            written_paths: list[Path] = []
            for chunk in plan.chunks:
                migration_path = planner.write_migration(
                    chunk.analysis,
                    rewrite_concurrent_indexes=plan.rewrite_concurrent_indexes,
                )
                written_paths.append(migration_path)
            self.stdout.write(self.style.SUCCESS(f"Wrote or reused {len(written_paths)} squash migration files."))
        else:
            self.stdout.write("")
            self.stdout.write("Dry run only. Re-run with `--write` to create migration files.")

    def _build_incremental_plan(
        self,
        planner: MigrationSquashPlanner,
        start_name: str,
        end_name: str,
        min_chunk_size: int,
        rewrite_concurrent_indexes: bool,
        bootstrap_policy_path: str | None,
    ) -> IncrementalPlan:
        scope = planner._requested_span(start_name, end_name)
        index_by_name = {name: idx for idx, name in enumerate(scope)}

        chunks: list[PlannedChunk] = []
        blockers: list[OperationBlocker] = []
        blocked_migrations: list[str] = []
        blocked_migration_set: set[str] = set()

        cursor = 0
        while cursor < len(scope):
            current_start = scope[cursor]
            analysis = planner.analyze_span(current_start, end_name)

            if analysis.included_span and analysis.state_equivalent:
                if len(analysis.included_span) < min_chunk_size:
                    self._append_blocker(
                        blockers=blockers,
                        blocked_migrations=blocked_migrations,
                        blocked_migration_set=blocked_migration_set,
                        blocker=OperationBlocker(
                            migration=current_start,
                            operation_index=0,
                            operation_type="ChunkSize",
                            reason=(
                                f"Chunk contains {len(analysis.included_span)} migration(s), "
                                f"below configured minimum chunk size {min_chunk_size}."
                            ),
                        ),
                    )
                    cursor += 1
                    continue
                chunks.append(PlannedChunk(analysis=analysis))
                cursor = index_by_name[analysis.included_end] + 1
                continue

            if analysis.included_span and not analysis.state_equivalent:
                split_candidate = self._largest_state_safe_prefix(
                    planner=planner,
                    start_name=current_start,
                    included_span=analysis.included_span,
                    min_chunk_size=min_chunk_size,
                )
                if split_candidate is not None:
                    chunks.append(
                        PlannedChunk(
                            analysis=split_candidate,
                            state_split_from_end=analysis.included_end,
                        )
                    )
                    cursor = index_by_name[split_candidate.included_end] + 1
                    continue

                blocker = OperationBlocker(
                    migration=current_start,
                    operation_index=0,
                    operation_type="StateVerification",
                    reason="Single migration is not state-equivalent after optimization.",
                )
                self._append_blocker(
                    blockers=blockers,
                    blocked_migrations=blocked_migrations,
                    blocked_migration_set=blocked_migration_set,
                    blocker=blocker,
                )
                cursor += 1
                continue

            if analysis.blockers:
                blocker_migration = analysis.blockers[0].migration
                blockers.extend(analysis.blockers)
                if blocker_migration not in blocked_migration_set:
                    blocked_migration_set.add(blocker_migration)
                    blocked_migrations.append(blocker_migration)
                cursor = index_by_name[blocker_migration] + 1
                continue

            synthetic_blocker = OperationBlocker(
                migration=current_start,
                operation_index=0,
                operation_type="Planner",
                reason="No squashable migrations in requested span and no explicit blockers were returned.",
            )
            self._append_blocker(
                blockers=blockers,
                blocked_migrations=blocked_migrations,
                blocked_migration_set=blocked_migration_set,
                blocker=synthetic_blocker,
            )
            cursor += 1

        covered = set(blocked_migrations)
        for chunk in chunks:
            covered.update(chunk.analysis.included_span)
        uncovered_migrations = [name for name in scope if name not in covered]

        total_operations = sum(self._migration_operation_count(planner, migration_name) for migration_name in scope)
        chunk_operations = sum(
            self._migration_operation_count(planner, migration_name)
            for chunk in chunks
            for migration_name in chunk.analysis.included_span
        )
        blocked_operations = sum(
            self._migration_operation_count(planner, migration_name) for migration_name in blocked_migrations
        )

        return IncrementalPlan(
            app_label=planner.app_label,
            start=start_name,
            end=end_name,
            min_chunk_size=min_chunk_size,
            rewrite_concurrent_indexes=rewrite_concurrent_indexes,
            bootstrap_policy_path=bootstrap_policy_path,
            scope=scope,
            chunks=chunks,
            blockers=blockers,
            blocked_migrations=blocked_migrations,
            uncovered_migrations=uncovered_migrations,
            total_operations=total_operations,
            chunk_operations=chunk_operations,
            blocked_operations=blocked_operations,
        )

    def _largest_state_safe_prefix(
        self,
        planner: MigrationSquashPlanner,
        start_name: str,
        included_span: list[str],
        min_chunk_size: int,
    ) -> SquashAnalysis | None:
        for candidate_end in reversed(included_span):
            candidate = planner.analyze_span(start_name, candidate_end)
            if candidate.included_end != candidate_end:
                raise ValueError(
                    f"Unexpected blocker while splitting state-unsafe span at '{start_name} -> {candidate_end}'."
                )
            if candidate.state_equivalent and len(candidate.included_span) >= min_chunk_size:
                return candidate
        return None

    def _append_blocker(
        self,
        blockers: list[OperationBlocker],
        blocked_migrations: list[str],
        blocked_migration_set: set[str],
        blocker: OperationBlocker,
    ) -> None:
        blockers.append(blocker)
        if blocker.migration not in blocked_migration_set:
            blocked_migration_set.add(blocker.migration)
            blocked_migrations.append(blocker.migration)

    def _migration_operation_count(self, planner: MigrationSquashPlanner, migration_name: str) -> int:
        return len(planner.loader.disk_migrations[(planner.app_label, migration_name)].operations)

    def _print_summary(self, plan: IncrementalPlan) -> None:
        self.stdout.write("")
        self.stdout.write("Incremental migration squash plan")
        self.stdout.write(f"  App: {plan.app_label}")
        self.stdout.write(f"  Scope: {plan.start} -> {plan.end}")
        self.stdout.write(f"  Scope migrations: {len(plan.scope)}")
        self.stdout.write(f"  Min chunk size: {plan.min_chunk_size}")
        self.stdout.write(f"  Rewrite concurrent indexes: {'yes' if plan.rewrite_concurrent_indexes else 'no'}")
        self.stdout.write(f"  Bootstrap policy: {plan.bootstrap_policy_path or 'none'}")
        self.stdout.write(f"  Chunks: {len(plan.chunks)}")
        self.stdout.write(f"  Blockers: {len(plan.blockers)}")
        self.stdout.write(f"  Covered migrations: {plan.covered_count}/{len(plan.scope)}")
        self.stdout.write(
            "  Operation coverage: "
            f"{plan.chunk_operations + plan.blocked_operations}/{plan.total_operations} "
            f"(chunked={plan.chunk_operations}, blocked={plan.blocked_operations})"
        )

        if plan.uncovered_migrations:
            self.stdout.write("")
            self.stdout.write("Uncovered migrations")
            for migration_name in plan.uncovered_migrations:
                self.stdout.write(f"  - {migration_name}")

    def _plan_to_json(self, plan: IncrementalPlan) -> dict:
        return {
            "app_label": plan.app_label,
            "start": plan.start,
            "end": plan.end,
            "min_chunk_size": plan.min_chunk_size,
            "rewrite_concurrent_indexes": plan.rewrite_concurrent_indexes,
            "bootstrap_policy_path": plan.bootstrap_policy_path,
            "scope_count": len(plan.scope),
            "scope": plan.scope,
            "chunk_count": len(plan.chunks),
            "chunks": [
                {
                    "start": chunk.analysis.included_start,
                    "end": chunk.analysis.included_end,
                    "migration_count": len(chunk.analysis.included_span),
                    "requested_start": chunk.analysis.requested_start,
                    "requested_end": chunk.analysis.requested_end,
                    "state_split_from_end": chunk.state_split_from_end,
                    "generated_migration_name": chunk.analysis.generated_migration_name,
                    "original_operation_count": chunk.analysis.original_operation_count,
                    "optimized_operation_count": chunk.analysis.optimized_operation_count,
                    "requires_non_atomic": chunk.analysis.requires_non_atomic,
                    "dependencies": chunk.analysis.dependencies,
                    "replaces": chunk.analysis.replaces,
                    "included_span": chunk.analysis.included_span,
                }
                for chunk in plan.chunks
            ],
            "blocker_count": len(plan.blockers),
            "blockers": [
                {
                    "migration": blocker.migration,
                    "operation_index": blocker.operation_index,
                    "operation_type": blocker.operation_type,
                    "nested_path": blocker.nested_path,
                    "fingerprint": blocker.fingerprint,
                    "reason": blocker.reason,
                }
                for blocker in plan.blockers
            ],
            "blocked_migrations_count": len(plan.blocked_migrations),
            "blocked_migrations": plan.blocked_migrations,
            "covered_count": plan.covered_count,
            "uncovered_count": len(plan.uncovered_migrations),
            "uncovered_migrations": plan.uncovered_migrations,
            "total_operations": plan.total_operations,
            "chunk_operations": plan.chunk_operations,
            "blocked_operations": plan.blocked_operations,
        }

    def _plan_to_markdown(self, plan: IncrementalPlan) -> str:
        lines = [
            "# Incremental migration squash plan",
            "",
            f"- Scope: `{plan.start}` -> `{plan.end}`",
            f"- Min chunk size: {plan.min_chunk_size}",
            f"- Rewrite concurrent indexes: {'yes' if plan.rewrite_concurrent_indexes else 'no'}",
            f"- Bootstrap policy: `{plan.bootstrap_policy_path}`"
            if plan.bootstrap_policy_path
            else "- Bootstrap policy: none",
            f"- Migrations in scope: {len(plan.scope)}",
            f"- Chunks: {len(plan.chunks)}",
            f"- Blockers: {len(plan.blockers)}",
            f"- Covered migrations: {plan.covered_count}/{len(plan.scope)}",
            (
                "- Operation coverage: "
                f"total={plan.total_operations}, chunked={plan.chunk_operations}, blocked={plan.blocked_operations}"
            ),
            "",
            "## Chunks",
        ]

        for index, chunk in enumerate(plan.chunks, start=1):
            split_note = ""
            if chunk.state_split_from_end:
                split_note = f" | split_from={chunk.state_split_from_end}"
            lines.append(
                f"{index}. `{chunk.analysis.included_start}` -> `{chunk.analysis.included_end}` "
                f"| migrations={len(chunk.analysis.included_span)} "
                f"| ops={chunk.analysis.original_operation_count}->{chunk.analysis.optimized_operation_count} "
                f"| atomic={'false' if chunk.analysis.requires_non_atomic else 'true'} "
                f"| file={chunk.analysis.generated_migration_name}.py{split_note}"
            )

        lines.append("")
        lines.append("## Blocked migrations")
        for migration_name in plan.blocked_migrations:
            lines.append(f"- `{migration_name}`")

        lines.append("")
        lines.append("## Blockers")
        for blocker in plan.blockers:
            path_note = f" path={blocker.nested_path}" if blocker.nested_path else ""
            lines.append(
                f"- `{blocker.migration}` op#{blocker.operation_index}{path_note} `{blocker.operation_type}`: {blocker.reason}"
            )

        if plan.uncovered_migrations:
            lines.append("")
            lines.append("## Uncovered migrations")
            for migration_name in plan.uncovered_migrations:
                lines.append(f"- `{migration_name}`")

        return "\n".join(lines) + "\n"

    def _plan_to_commands(
        self,
        plan: IncrementalPlan,
        app_label: str,
        bootstrap_policy_path: Path | None,
    ) -> str:
        lines = [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
        ]
        for index, chunk in enumerate(plan.chunks, start=1):
            lines.append(f"# Chunk {index}: {chunk.analysis.included_start} -> {chunk.analysis.included_end}")
            lines.append(
                "DEBUG=1 SERVER_GATEWAY_INTERFACE=ASGI "
                "python manage.py build_migration_squash "
                f"--app {app_label} "
                f"--start {chunk.analysis.included_start} "
                f"--end {chunk.analysis.included_end} "
                f"{f'--bootstrap-policy {shlex.quote(str(bootstrap_policy_path))} ' if bootstrap_policy_path else ''}"
                f"{'--rewrite-concurrent-indexes ' if plan.rewrite_concurrent_indexes else ''}"
                "--write"
            )
            lines.append("")
        return "\n".join(lines)
