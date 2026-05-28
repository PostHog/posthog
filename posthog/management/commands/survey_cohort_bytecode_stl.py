"""Survey the HogVM bytecode of production realtime cohorts (Behavioral Cohorts rebuild, M0).

This is the keystone Phase-0 measurement: it walks every `cohort_type='realtime' AND
deleted=false` cohort's `filters` JSON, disassembles each leaf's compiled `bytecode`, and
aggregates two histograms:

  (a) STL-function frequency — how often each `CALL_GLOBAL "<name>"` appears, and how many
      distinct cohorts use it.
  (b) opcode frequency — how often each opcode is used, and how many distinct cohorts use it.

It then cross-references both against the Rust HogVM's capabilities to produce the
`rust_gaps` section — the authoritative input that sizes the M8.a missing-natives work
(predicted minimum: just `isNull`). Output is written to `cohort_bytecode_survey.json`.

Run against a fresh `posthog_cohort` snapshot so the result is reproducible:

    ./manage.py survey_cohort_bytecode_stl --output cohort_bytecode_survey.json
"""

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any

from django.core.management.base import BaseCommand

import structlog

from posthog.models.cohort.cohort import Cohort, CohortType

from common.hogvm.python.operation import HOGQL_BYTECODE_IDENTIFIER, HOGQL_BYTECODE_IDENTIFIER_V0, Operation

logger = structlog.get_logger(__name__)

# Number of inline operands that follow each opcode in the flat bytecode list. Sourced from
# common/hogvm/python/debugger.py:color_bytecode (the authoritative disassembler) and
# common/hogvm/python/operation.py. CLOSURE is variable-length and handled separately below.
# MOD is included here (color_bytecode omits it, but it is a valid 0-operand binary op).
FIXED_OPERAND_COUNTS: dict[Operation, int] = {
    Operation.GET_GLOBAL: 1,
    Operation.CALL_GLOBAL: 2,
    Operation.AND: 1,
    Operation.OR: 1,
    Operation.NOT: 0,
    Operation.PLUS: 0,
    Operation.MINUS: 0,
    Operation.MULTIPLY: 0,
    Operation.DIVIDE: 0,
    Operation.MOD: 0,
    Operation.EQ: 0,
    Operation.NOT_EQ: 0,
    Operation.GT: 0,
    Operation.GT_EQ: 0,
    Operation.LT: 0,
    Operation.LT_EQ: 0,
    Operation.LIKE: 0,
    Operation.ILIKE: 0,
    Operation.NOT_LIKE: 0,
    Operation.NOT_ILIKE: 0,
    Operation.IN: 0,
    Operation.NOT_IN: 0,
    Operation.REGEX: 0,
    Operation.NOT_REGEX: 0,
    Operation.IREGEX: 0,
    Operation.NOT_IREGEX: 0,
    Operation.IN_COHORT: 0,
    Operation.NOT_IN_COHORT: 0,
    Operation.TRUE: 0,
    Operation.FALSE: 0,
    Operation.NULL: 0,
    Operation.STRING: 1,
    Operation.INTEGER: 1,
    Operation.FLOAT: 1,
    Operation.POP: 0,
    Operation.GET_LOCAL: 1,
    Operation.SET_LOCAL: 1,
    Operation.RETURN: 0,
    Operation.JUMP: 1,
    Operation.JUMP_IF_FALSE: 1,
    Operation.DECLARE_FN: 3,
    Operation.DICT: 1,
    Operation.ARRAY: 1,
    Operation.TUPLE: 1,
    Operation.GET_PROPERTY: 0,
    Operation.SET_PROPERTY: 0,
    Operation.JUMP_IF_STACK_NOT_NULL: 1,
    Operation.GET_PROPERTY_NULLISH: 0,
    Operation.THROW: 0,
    Operation.TRY: 1,
    Operation.POP_TRY: 0,
    Operation.CALLABLE: 4,
    Operation.CALL_LOCAL: 1,
    Operation.GET_UPVALUE: 1,
    Operation.SET_UPVALUE: 1,
    Operation.CLOSE_UPVALUE: 0,
}

# Snapshot of the Rust HogVM's evaluation surface, used only to annotate the survey with the
# `rust_gaps` section. Source of truth: rust/common/hogvm/src/stl.rs (regenerate the natives
# list via `bin/dump_hogvmrs_stl`). Cross-check these against the Rust source when reading the
# survey — they are a snapshot, not a live import (kept here to avoid a cross-product import).
RUST_NATIVE_STL: frozenset[str] = frozenset(
    {
        "toString",
        "typeof",
        "isNull",  # added in M8.a
        "values",
        "length",
        "arrayPushBack",
        "arrayPushFront",
        "arrayPopBack",
        "arrayPopFront",
        "arraySort",
        "arrayReverse",
        "arrayReverseSort",
        "arrayStringConcat",
        "has",
        "indexOf",
        "notEmpty",
        "match",
        "extractRegex",
        "JSONExtract",
        "multiSearchAnyCaseInsensitive",
        "randomFloat",
    }
)
# Hog-bytecode-backed STL functions (rust/common/hogvm/src/stl.rs:hog_stl).
RUST_HOG_STL: frozenset[str] = frozenset(
    {"arrayCount", "arrayExists", "arrayFilter", "arrayMap", "arrayReduce", "sortableSemver"}
)
RUST_SUPPORTED_STL: frozenset[str] = RUST_NATIVE_STL | RUST_HOG_STL

# `sortableSemver`'s hog body itself calls these natives, which are NOT registered in the Rust
# STL — so any cohort that uses a SEMVER_* operator is transitively blocked until they land
# (TDD §5.2). A cohort's top-level bytecode only shows `sortableSemver`, so we surface the
# transitive gap explicitly.
SORTABLE_SEMVER_TRANSITIVE_DEPS: frozenset[str] = frozenset({"empty", "splitByString", "toInt"})

# Opcodes the Rust HogVM dispatch returns NotImplemented for (rust/common/hogvm/src/vm.rs).
RUST_NOT_IMPLEMENTED_OPCODES: frozenset[Operation] = frozenset(
    {Operation.DECLARE_FN, Operation.IN_COHORT, Operation.NOT_IN_COHORT}
)


def iter_instructions(bytecode: list[Any]) -> Iterator[tuple[Operation, list[Any]]]:
    """Disassemble a HogVM bytecode program, yielding (opcode, operands) per instruction.

    Mirrors the operand layout of common/hogvm/python/debugger.py:color_bytecode. Raises
    ValueError on an unknown opcode or truncated instruction so a malformed program is
    recorded as a walk failure rather than silently miscounted.
    """
    n = len(bytecode)
    ip = 0
    # Skip the header: "_H" carries a trailing version int; "_h" (v0) does not.
    if n > 0 and bytecode[0] == HOGQL_BYTECODE_IDENTIFIER:
        ip = 2
    elif n > 0 and bytecode[0] == HOGQL_BYTECODE_IDENTIFIER_V0:
        ip = 1

    while ip < n:
        raw = bytecode[ip]
        try:
            op = Operation(raw)
        except ValueError as e:
            raise ValueError(f"unknown opcode {raw!r} at index {ip}") from e

        if op == Operation.CLOSURE:
            if ip + 1 >= n:
                raise ValueError(f"truncated CLOSURE at index {ip}")
            upvalue_count = bytecode[ip + 1]
            if not isinstance(upvalue_count, int):
                raise ValueError(f"CLOSURE upvalue count is not an int at index {ip + 1}")
            consumed = 1 + 2 * upvalue_count
        else:
            consumed = FIXED_OPERAND_COUNTS[op]

        if ip + 1 + consumed > n:
            raise ValueError(f"truncated operands for {op.name} at index {ip}")

        operands = bytecode[ip + 1 : ip + 1 + consumed]
        yield op, operands
        ip += 1 + consumed


def iter_bytecode_leaves(properties: Any) -> Iterator[dict[str, Any]]:
    """Walk a cohort's `filters.properties` AND/OR tree, yielding leaves with populated bytecode."""
    if not isinstance(properties, dict):
        return
    if properties.get("type") in ("AND", "OR") and isinstance(properties.get("values"), list):
        for child in properties["values"]:
            yield from iter_bytecode_leaves(child)
        return
    # Leaf node.
    if properties.get("bytecode"):
        yield properties


def _normalize_bytecode(raw: Any) -> list[Any] | None:
    """Coerce an inline `bytecode` value to a list; cohorts store a list, but tolerate a JSON string."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, list) else None
    return None


def aggregate_survey(cohort_rows: Iterable[tuple[int, int, dict[str, Any] | None]]) -> dict[str, Any]:
    """Aggregate opcode + STL-function histograms across cohort bytecode. Pure (no DB / I/O)."""
    opcode_counts: Counter[str] = Counter()
    opcode_cohorts: dict[str, set[int]] = defaultdict(set)
    stl_counts: Counter[str] = Counter()
    stl_cohorts: dict[str, set[int]] = defaultdict(set)

    teams_scanned: set[int] = set()
    cohorts_scanned = 0
    cohorts_with_bytecode: set[int] = set()
    leaves_with_bytecode = 0
    leaves_walked_ok = 0
    leaves_walk_failed = 0
    unique_condition_hashes: set[str] = set()
    leaf_type_counts: Counter[str] = Counter()
    walk_failures: list[dict[str, Any]] = []

    for cohort_id, team_id, filters in cohort_rows:
        cohorts_scanned += 1
        teams_scanned.add(team_id)
        properties = (filters or {}).get("properties") if isinstance(filters, dict) else None

        for leaf in iter_bytecode_leaves(properties):
            leaves_with_bytecode += 1
            cohorts_with_bytecode.add(cohort_id)
            leaf_type_counts[str(leaf.get("type", "unknown"))] += 1
            condition_hash = leaf.get("conditionHash")
            if isinstance(condition_hash, str):
                unique_condition_hashes.add(condition_hash)

            bytecode = _normalize_bytecode(leaf.get("bytecode"))
            if bytecode is None:
                leaves_walk_failed += 1
                walk_failures.append(
                    {"cohort_id": cohort_id, "team_id": team_id, "error": "bytecode is not a list/JSON-array"}
                )
                continue

            try:
                # Materialize first so a mid-walk failure doesn't half-count this leaf.
                instructions = list(iter_instructions(bytecode))
            except ValueError as e:
                leaves_walk_failed += 1
                walk_failures.append({"cohort_id": cohort_id, "team_id": team_id, "error": str(e)})
                continue

            leaves_walked_ok += 1
            for op, operands in instructions:
                opcode_counts[op.name] += 1
                opcode_cohorts[op.name].add(cohort_id)
                if op == Operation.CALL_GLOBAL and operands and isinstance(operands[0], str):
                    name = operands[0]
                    stl_counts[name] += 1
                    stl_cohorts[name].add(cohort_id)

    stl_functions = [
        {
            "name": name,
            "call_count": count,
            "distinct_cohorts": len(stl_cohorts[name]),
            "in_rust_stl": name in RUST_SUPPORTED_STL,
        }
        for name, count in stl_counts.most_common()
    ]
    opcodes = [
        {
            "opcode": name,
            "id": int(Operation[name].value),
            "count": count,
            "distinct_cohorts": len(opcode_cohorts[name]),
            "rust_not_implemented": Operation[name] in RUST_NOT_IMPLEMENTED_OPCODES,
        }
        for name, count in opcode_counts.most_common()
    ]

    missing_natives = sorted({name for name in stl_counts if name not in RUST_SUPPORTED_STL})
    transitive_semver = sorted(SORTABLE_SEMVER_TRANSITIVE_DEPS) if "sortableSemver" in stl_counts else []
    not_implemented_used = sorted({name for name in opcode_counts if Operation[name] in RUST_NOT_IMPLEMENTED_OPCODES})

    return {
        "totals": {
            "cohorts_scanned": cohorts_scanned,
            "teams_scanned": len(teams_scanned),
            "cohorts_with_bytecode_leaves": len(cohorts_with_bytecode),
            "leaves_with_bytecode": leaves_with_bytecode,
            "leaves_walked_ok": leaves_walked_ok,
            "leaves_walk_failed": leaves_walk_failed,
            "unique_condition_hashes": len(unique_condition_hashes),
        },
        "leaf_types": dict(leaf_type_counts.most_common()),
        "stl_functions": stl_functions,
        "opcodes": opcodes,
        "rust_gaps": {
            "missing_stl_natives": missing_natives,
            "sortable_semver_transitive_deps": transitive_semver,
            "not_implemented_opcodes_used": not_implemented_used,
        },
        "walk_failures": walk_failures,
    }


class Command(BaseCommand):
    help = "Survey HogVM bytecode (STL functions + opcodes) across production realtime cohorts (M0)"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--output",
            type=str,
            default="cohort_bytecode_survey.json",
            help="Path to write the survey JSON (default: cohort_bytecode_survey.json)",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="Restrict the survey to a single team_id (optional)",
        )
        parser.add_argument(
            "--include-deleted",
            action="store_true",
            help="Include soft-deleted cohorts (default: only deleted=false)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        output_path: str = options["output"]
        team_id: int | None = options.get("team_id")
        include_deleted: bool = options.get("include_deleted", False)

        queryset = Cohort.objects.filter(cohort_type=CohortType.REALTIME)
        if not include_deleted:
            queryset = queryset.filter(deleted=False)
        if team_id is not None:
            queryset = queryset.filter(team_id=team_id)

        rows = queryset.values_list("id", "team_id", "filters").iterator(chunk_size=500)
        result = aggregate_survey((cohort_id, tid, filters) for cohort_id, tid, filters in rows)

        result["generated_at"] = datetime.now(UTC).isoformat()
        result["scope"] = {
            "cohort_type": str(CohortType.REALTIME),
            "deleted": None if include_deleted else False,
            "team_id": team_id,
        }

        with open(output_path, "w") as f:
            json.dump(result, f, indent=2, sort_keys=False)

        totals = result["totals"]
        logger.info(
            "cohort_bytecode_survey_complete",
            output=output_path,
            cohorts_scanned=totals["cohorts_scanned"],
            leaves_walked_ok=totals["leaves_walked_ok"],
            leaves_walk_failed=totals["leaves_walk_failed"],
            missing_stl_natives=result["rust_gaps"]["missing_stl_natives"],
            not_implemented_opcodes_used=result["rust_gaps"]["not_implemented_opcodes_used"],
        )

        self.stdout.write(self.style.SUCCESS(f"Wrote survey to {output_path}"))
        self.stdout.write(
            f"  cohorts scanned: {totals['cohorts_scanned']} "
            f"({totals['cohorts_with_bytecode_leaves']} with bytecode leaves)"
        )
        self.stdout.write(
            f"  bytecode leaves: {totals['leaves_with_bytecode']} "
            f"(walked ok: {totals['leaves_walked_ok']}, failed: {totals['leaves_walk_failed']})"
        )
        self.stdout.write(f"  unique conditionHashes: {totals['unique_condition_hashes']}")
        gaps = result["rust_gaps"]
        self.stdout.write(f"  rust missing STL natives: {gaps['missing_stl_natives'] or 'none'}")
        if gaps["sortable_semver_transitive_deps"]:
            self.stdout.write(f"  sortableSemver transitive deps needed: {gaps['sortable_semver_transitive_deps']}")
        self.stdout.write(f"  rust NotImplemented opcodes used: {gaps['not_implemented_opcodes_used'] or 'none'}")
