"""Classify every person and mapping of one team in fixed key order, into resumable per-chunk row files.

A scan directory holds a plan and the files of each ClickHouse chunk. Each chunk runs two phases in
ClickHouse primary key order:
- persons: ClickHouse persons by (team_id, id), compared with Postgres by uuid.
- mappings: ClickHouse mappings by (team_id, distinct_id), compared with Postgres by distinct id.
Each phase also writes the hash of every key it classified, for a later pass over Postgres.

Every page is classified completely, appended to the rows file, and only then recorded in the cursor, so a
run that stops resumes at the first page it did not record. Rows hold the raw keys a repair needs, so the
scan directory is private to the user who runs the scan.
"""

from __future__ import annotations

import os
import json
import stat
import time
import hashlib
import dataclasses
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np

from posthog.dataclasses import frozen
from posthog.models.person.divergence import lookups, observe
from posthog.models.person.divergence.flavors import Verdict, classify_mapping, classify_person
from posthog.models.person.divergence.inspection import ghost_era, hash_distinct_id
from posthog.models.team import Team

PLAN_VERSION = 1
PLAN_FILE = "plan.json"

KeyKind = Literal["person", "mapping"]
ChPhase = Literal["persons", "mappings"]
CH_PHASES: tuple[ChPhase, ...] = ("persons", "mappings")
DONE = "done"

# The smallest uuid and distinct id. A chunk's first page starts at its lower bound inclusive.
_FIRST_PERSON_KEY = "00000000-0000-0000-0000-000000000000"
_FIRST_MAPPING_KEY = ""

_READ_SETTINGS = {"apply_deleted_mask": 0, "max_execution_time": 120}
_SAMPLE_PER_CHUNK = 200

_PERSON_PAGE_END = """
SELECT count(), toString(max(id)) FROM (
    SELECT id FROM person
    WHERE team_id = %(team_id)s AND id {op} toUUID(%(after)s){upper}
    ORDER BY id LIMIT %(rows)s
)
"""
_MAPPING_PAGE_END = """
SELECT count(), max(distinct_id) FROM (
    SELECT distinct_id FROM person_distinct_id2
    WHERE team_id = %(team_id)s AND distinct_id {op} %(after)s{upper}
    ORDER BY distinct_id LIMIT %(rows)s
)
"""
# Keyed by (phase, first page, bounded above). The page query reads in primary key order and stops at
# the row limit, and returns only the last key, so a page never sends keys back to the client.
_PAGE_END_SQL = {
    (phase, first, bounded): template.replace("{op}", ">=" if first else ">").replace(
        "{upper}", f" AND {column} < {cast}" if bounded else ""
    )
    for phase, template, column, cast in (
        ("persons", _PERSON_PAGE_END, "id", "toUUID(%(upper)s)"),
        ("mappings", _MAPPING_PAGE_END, "distinct_id", "%(upper)s"),
    )
    for first in (True, False)
    for bounded in (True, False)
}

# arraySort orders the sample with ClickHouse's own comparison, which the page queries also use.
_SAMPLE_SQL = {
    "persons": """
        SELECT arrayMap(x -> toString(x), arraySort(groupArraySample(%(size)s, 1)(id)))
        FROM person WHERE team_id = %(team_id)s
    """,
    "mappings": """
        SELECT arraySort(groupArraySample(%(size)s, 1)(distinct_id))
        FROM person_distinct_id2 WHERE team_id = %(team_id)s
    """,
}


class ScanError(Exception):
    pass


@frozen
class KeyBounds:
    # Inclusive lower and exclusive upper bound; None is open.
    lower: str | None
    upper: str | None


@frozen
class PageResult:
    rows: list[dict[str, Any]]
    # Hashes of every key the page classified, for the Postgres phase's key sets.
    keys: list[int]
    counts: Counter[str]


@frozen
class ChunkBounds:
    # Inclusive lower and exclusive upper bound per ClickHouse phase; None is open.
    person_from: str | None
    person_to: str | None
    mapping_from: str | None
    mapping_to: str | None

    def bounds(self, phase: ChPhase) -> KeyBounds:
        if phase == "persons":
            return KeyBounds(lower=self.person_from, upper=self.person_to)
        return KeyBounds(lower=self.mapping_from, upper=self.mapping_to)


@frozen
class ScanPlan:
    version: int
    team_id: int
    team_exists: bool
    created_at: str
    # When the team's Postgres persons were purged, if ever; dates ghosts.
    purged_at: str | None
    chunks: tuple[ChunkBounds, ...]
    ch_page_rows: int
    pg_page_size: int

    def purged_at_datetime(self) -> datetime | None:
        return None if self.purged_at is None else datetime.fromisoformat(self.purged_at)

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ScanPlan:
        if data.get("version") != PLAN_VERSION:
            raise ScanError(f"plan version {data.get('version')} is not {PLAN_VERSION}")
        return cls(**{**data, "chunks": tuple(ChunkBounds(**c) for c in data["chunks"])})


@dataclasses.dataclass(frozen=False)
class Cursor:
    # A ClickHouse phase name, "postgres", or "done".
    phase: str
    # The last key the phase finished; None before its first page.
    after: str | None = None
    rows_bytes: int = 0
    person_keys_bytes: int = 0
    mapping_keys_bytes: int = 0
    pages: int = 0
    # Classified keys by "kind/flavor/sub_flavor", including the ok ones the rows file leaves out.
    counts: dict[str, int] = dataclasses.field(default_factory=dict)
    updated_at: str | None = None


@frozen
class RunFiles:
    rows: Path
    cursor: Path
    person_keys: Path | None
    mapping_keys: Path | None


def chunk_files(scan_dir: Path, chunk: int) -> RunFiles:
    return RunFiles(
        rows=scan_dir / f"chunk-{chunk}.rows.jsonl",
        cursor=scan_dir / f"chunk-{chunk}.cursor.json",
        person_keys=scan_dir / f"chunk-{chunk}.person-keys.u64",
        mapping_keys=scan_dir / f"chunk-{chunk}.mapping-keys.u64",
    )


def key_hash(key: str) -> int:
    """A 64-bit hash of a uuid or distinct id, for the key sets the Postgres phase checks against."""
    return int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "little")


def _private_dir(scan_dir: Path, *, create: bool = False) -> None:
    """Check that the scan directory is a real directory that only this user owns and can read, because its rows
    hold raw customer keys. With `create`, a missing directory is created that way first."""
    if create and not os.path.lexists(scan_dir):
        scan_dir.mkdir(mode=0o700, parents=True)
    info = scan_dir.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ScanError(f"{scan_dir} is not a directory; choose a new directory for the scan")
    if info.st_uid != os.geteuid():
        raise ScanError(f"{scan_dir} is owned by another user; choose a new directory for the scan")
    if info.st_mode & 0o077:
        raise ScanError(f"{scan_dir} is readable by other users; choose a new directory for the scan")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    os.replace(tmp, path)


def load_plan(scan_dir: Path) -> ScanPlan:
    path = scan_dir / PLAN_FILE
    if not path.exists():
        raise ScanError(f"{path} does not exist; create a plan first")
    # Every run and verb loads the plan, so each re-checks the directory before it writes or reads rows.
    _private_dir(scan_dir)
    return ScanPlan.from_json(json.loads(path.read_text()))


def load_cursor(path: Path) -> Cursor | None:
    return Cursor(**json.loads(path.read_text())) if path.exists() else None


def _sample_bounds(team_id: int, phase: ChPhase, chunks: int) -> list[str]:
    rows = lookups._ch(_SAMPLE_SQL[phase], {"team_id": team_id, "size": chunks * _SAMPLE_PER_CHUNK}, _READ_SETTINGS)
    sample = list(rows[0][0]) if rows else []
    bounds: list[str] = []
    for k in range(1, chunks):
        if not sample:
            break
        candidate = sample[k * len(sample) // chunks]
        if not bounds or candidate != bounds[-1]:
            bounds.append(candidate)
    return bounds


def _phase_edges(bounds: list[str], chunks: int, first_key: str) -> list[KeyBounds]:
    points: list[str | None] = [None, *bounds, None]
    edges = [KeyBounds(lower=points[i], upper=points[i + 1]) for i in range(len(points) - 1)]
    # A small team can yield fewer distinct bounds than chunks. The extra chunks get an empty range.
    empty = bounds[-1] if bounds else first_key
    return edges + [KeyBounds(lower=empty, upper=empty)] * (chunks - len(edges))


def _chunks_from_bounds(person_bounds: list[str], mapping_bounds: list[str], chunks: int) -> tuple[ChunkBounds, ...]:
    persons = _phase_edges(person_bounds, chunks, _FIRST_PERSON_KEY)
    mappings = _phase_edges(mapping_bounds, chunks, _FIRST_MAPPING_KEY)
    return tuple(
        ChunkBounds(person_from=p.lower, person_to=p.upper, mapping_from=m.lower, mapping_to=m.upper)
        for p, m in zip(persons, mappings)
    )


def create_plan(
    scan_dir: Path,
    team_id: int,
    *,
    chunks: int = 1,
    purged_at: datetime | None = None,
    ch_page_rows: int = 100_000,
    pg_page_size: int = 5_000,
) -> ScanPlan:
    """Write a scan plan. Chunk bounds come from one sample of the team's keys, taken once, so every
    chunk run of the scan shares the same bounds."""
    if (scan_dir / PLAN_FILE).exists():
        raise ScanError(f"{scan_dir / PLAN_FILE} already exists")
    _private_dir(scan_dir, create=True)
    if chunks > 1:
        bounds = _chunks_from_bounds(
            _sample_bounds(team_id, "persons", chunks), _sample_bounds(team_id, "mappings", chunks), chunks
        )
    else:
        bounds = (ChunkBounds(person_from=None, person_to=None, mapping_from=None, mapping_to=None),)
    plan = ScanPlan(
        version=PLAN_VERSION,
        team_id=team_id,
        team_exists=Team.objects.filter(id=team_id).exists(),
        created_at=_now(),
        purged_at=None if purged_at is None else purged_at.isoformat(),
        chunks=bounds,
        ch_page_rows=ch_page_rows,
        pg_page_size=pg_page_size,
    )
    _write_json_atomic(scan_dir / PLAN_FILE, plan.to_json())
    return plan


class _RunWriter:
    """Appends a page's rows and key hashes, then records the page in the cursor.

    Opening it truncates every file to the offsets the cursor recorded, which drops a page that was
    written but not recorded before a run stopped.
    """

    def __init__(self, files: RunFiles, cursor: Cursor) -> None:
        self.files = files
        self.cursor = cursor
        self._handles: dict[str, Any] = {}
        for name, path, offset in (
            ("rows", files.rows, cursor.rows_bytes),
            ("person_keys", files.person_keys, cursor.person_keys_bytes),
            ("mapping_keys", files.mapping_keys, cursor.mapping_keys_bytes),
        ):
            if path is None:
                continue
            path.touch(exist_ok=True)
            os.truncate(path, offset)
            self._handles[name] = path.open("ab")

    def commit(
        self,
        rows: Sequence[dict[str, Any]],
        *,
        person_keys: Sequence[int] = (),
        mapping_keys: Sequence[int] = (),
        counts: Counter[str],
        after: str | None,
        phase: str,
    ) -> None:
        self._handles["rows"].write(b"".join(json.dumps(r, sort_keys=True).encode() + b"\n" for r in rows))
        for name, keys in (("person_keys", person_keys), ("mapping_keys", mapping_keys)):
            if keys:
                np.asarray(keys, dtype="<u8").tofile(self._handles[name])
        for handle in self._handles.values():
            handle.flush()
            os.fsync(handle.fileno())
        cursor = self.cursor
        cursor.rows_bytes = self._handles["rows"].tell()
        if "person_keys" in self._handles:
            cursor.person_keys_bytes = self._handles["person_keys"].tell()
            cursor.mapping_keys_bytes = self._handles["mapping_keys"].tell()
        for key, n in counts.items():
            cursor.counts[key] = cursor.counts.get(key, 0) + n
        cursor.after = after
        cursor.phase = phase
        cursor.pages += 1
        cursor.updated_at = _now()
        _write_json_atomic(self.files.cursor, dataclasses.asdict(cursor))

    def finish_phase(self, next_phase: str) -> None:
        self.cursor.phase = next_phase
        self.cursor.after = None
        self.cursor.updated_at = _now()
        _write_json_atomic(self.files.cursor, dataclasses.asdict(self.cursor))

    def close(self) -> None:
        for handle in self._handles.values():
            handle.close()


def _state(state: Any) -> dict[str, Any] | None:
    return None if state is None else dataclasses.asdict(state)


def _row(
    *,
    kind: KeyKind,
    team_id: int,
    key: str,
    verdict: Verdict,
    phase: str,
    observed_at: str,
    pg: Any,
    ch: Any,
    ch_owner_pg_state: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "team_id": team_id,
        "key": key,
        # Safe to share: distinct ids are customer data, their hash is not.
        "key_hash": hash_distinct_id(team_id, key) if kind == "mapping" else None,
        "flavor": verdict.flavor,
        "sub_flavor": verdict.sub_flavor,
        "verb": verdict.verb,
        "group": None,
        "also": [],
        "phase": phase,
        "observed_at": observed_at,
        "evidence": {"pg": _state(pg), "ch": _state(ch), "ch_owner_pg_state": ch_owner_pg_state},
    }


def _count_key(kind: str, verdict: Verdict) -> str:
    return f"{kind}/{verdict.flavor}/{verdict.sub_flavor or '-'}"


def _reported(verdict: Verdict) -> bool:
    return verdict.flavor not in ("ok", "ok_deleted")


def _page_end(plan: ScanPlan, phase: ChPhase, after: str, first: bool, upper: str | None) -> tuple[int, str | None]:
    sql = _PAGE_END_SQL[(phase, first, upper is not None)]
    args: dict[str, Any] = {"team_id": plan.team_id, "after": after, "rows": plan.ch_page_rows}
    if upper is not None:
        args["upper"] = upper
    rows = lookups._ch(sql, args, _READ_SETTINGS)
    count = int(rows[0][0]) if rows else 0
    return count, (str(rows[0][1]) if count else None)


def _classify_persons_page(plan: ScanPlan, after: str, last: str, first: bool) -> PageResult:
    observed_at = _now()
    ch = observe.ch_person_states_in_range(plan.team_id, after, last, first=first)
    uuids = list(ch)
    pg = observe.pg_person_states(plan.team_id, uuids) if plan.team_exists and uuids else {}
    purged_at = plan.purged_at_datetime()
    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for person_uuid, ch_state in ch.items():
        pg_state = pg.get(person_uuid)
        verdict = classify_person(
            pg_state,
            ch_state,
            team_exists=plan.team_exists,
            ghost_era=ghost_era(ch_state.newest_written_at, purged_at),
        )
        counts[_count_key("person", verdict)] += 1
        if _reported(verdict):
            rows.append(
                _row(
                    kind="person",
                    team_id=plan.team_id,
                    key=person_uuid,
                    verdict=verdict,
                    phase="persons",
                    observed_at=observed_at,
                    pg=pg_state,
                    ch=ch_state,
                )
            )
    return PageResult(rows=rows, keys=[key_hash(u) for u in uuids], counts=counts)


def _classify_mappings_page(plan: ScanPlan, after: str, last: str, first: bool) -> PageResult:
    observed_at = _now()
    ch = observe.ch_mapping_states_in_range(plan.team_id, after, last, first=first)
    distinct_ids = list(ch)
    pg = observe.pg_mapping_rows(plan.team_id, distinct_ids) if plan.team_exists and distinct_ids else {}
    # Only ghost and diverged mappings need their ClickHouse owner's Postgres state.
    owners = sorted(
        {
            state.winner_person_uuid
            for distinct_id, state in ch.items()
            if pg.get(distinct_id) is None or pg[distinct_id].person_uuid != state.winner_person_uuid
        }
    )
    owner_states = observe.pg_person_states(plan.team_id, owners) if plan.team_exists and owners else {}
    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for distinct_id, ch_state in ch.items():
        pg_row = pg.get(distinct_id)
        owner_state = observe.person_pg_state(owner_states, ch_state.winner_person_uuid)
        verdict = classify_mapping(pg_row, ch_state, ch_owner_pg_state=owner_state)
        counts[_count_key("mapping", verdict)] += 1
        if _reported(verdict):
            rows.append(
                _row(
                    kind="mapping",
                    team_id=plan.team_id,
                    key=distinct_id,
                    verdict=verdict,
                    phase="mappings",
                    observed_at=observed_at,
                    pg=pg_row,
                    ch=ch_state,
                    ch_owner_pg_state=owner_state,
                )
            )
    return PageResult(rows=rows, keys=[key_hash(d) for d in distinct_ids], counts=counts)


_PAGE_CLASSIFIERS: dict[ChPhase, Callable[..., PageResult]] = {
    "persons": _classify_persons_page,
    "mappings": _classify_mappings_page,
}


def run_chunk(
    scan_dir: Path,
    chunk: int,
    *,
    resume: bool,
    pause_seconds: float = 0.0,
    log: Callable[[str], None] = lambda _: None,
) -> Cursor:
    """Run both ClickHouse phases of one chunk to the end, or resume them from the cursor."""
    plan = load_plan(scan_dir)
    if not 0 <= chunk < len(plan.chunks):
        raise ScanError(f"chunk {chunk} is not in the plan's {len(plan.chunks)} chunks")
    files = chunk_files(scan_dir, chunk)
    cursor = load_cursor(files.cursor)
    if cursor is not None and not resume:
        raise ScanError(f"{files.cursor} exists; pass resume to continue it")
    cursor = cursor or Cursor(phase=CH_PHASES[0])
    writer = _RunWriter(files, cursor)
    try:
        while cursor.phase != DONE:
            phase: ChPhase = "persons" if cursor.phase == "persons" else "mappings"
            bounds = plan.chunks[chunk].bounds(phase)
            lower, upper = bounds.lower, bounds.upper
            first = cursor.after is None
            after = cursor.after if cursor.after is not None else (lower if lower is not None else _first_key(phase))
            count, last = _page_end(plan, phase, after, first, upper)
            if last is None:
                writer.finish_phase(_next_phase(phase))
                log(f"chunk {chunk} {phase}: done")
                continue
            page = _PAGE_CLASSIFIERS[phase](plan, after, last, first)
            rows, keys, counts = page.rows, page.keys, page.counts
            writer.commit(
                rows,
                person_keys=keys if phase == "persons" else (),
                mapping_keys=keys if phase == "mappings" else (),
                counts=counts,
                after=last,
                phase=phase,
            )
            log(f"chunk {chunk} {phase}: page {cursor.pages}, {len(keys)} keys, {len(rows)} reported")
            if count < plan.ch_page_rows:
                writer.finish_phase(_next_phase(phase))
                log(f"chunk {chunk} {phase}: done")
            elif pause_seconds:
                time.sleep(pause_seconds)
    finally:
        writer.close()
    return cursor


def _first_key(phase: ChPhase) -> str:
    return _FIRST_PERSON_KEY if phase == "persons" else _FIRST_MAPPING_KEY


def _next_phase(phase: ChPhase) -> str:
    return "mappings" if phase == "persons" else DONE
