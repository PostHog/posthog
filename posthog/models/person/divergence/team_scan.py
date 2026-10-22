"""Classify every person and mapping of one team, in ClickHouse primary key order, and write a resumable report.

Each chunk reads persons by (team_id, id) and mappings by (team_id, distinct_id) and compares them with Postgres.
A Postgres pass then lists persons by id and reports only what ClickHouse has no row for, so it runs after every
chunk. A page is recorded in the cursor only after its rows are written, so a stopped run resumes at the first
unrecorded page. Rows hold raw keys, so the scan directory is private to its owner; the summary carries none.
"""

from __future__ import annotations

import os
import json
import stat
import time
import fcntl
import hashlib
import dataclasses
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import numpy as np

from posthog.dataclasses import frozen
from posthog.models.person.divergence import lookups, observe
from posthog.models.person.divergence.flavors import (
    PERSON_VERBS,
    PgMapping,
    PgPerson,
    Verdict,
    classify_mapping,
    classify_person,
)
from posthog.models.person.divergence.inspection import ghost_era, hash_distinct_id
from posthog.models.person.util import list_persons_for_team
from posthog.models.team import Team

PLAN_VERSION = 1
PLAN_FILE = "plan.json"
REPORT_FILE = "report.jsonl"
SUMMARY_FILE = "summary.json"

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
class IdRange:
    # Postgres person ids in [start, end).
    start: int
    end: int


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


def postgres_files(scan_dir: Path, id_range: IdRange | None) -> RunFiles:
    name = "postgres" if id_range is None else f"postgres-{id_range.start}-{id_range.end}"
    return RunFiles(
        rows=scan_dir / f"{name}.rows.jsonl",
        cursor=scan_dir / f"{name}.cursor.json",
        person_keys=None,
        mapping_keys=None,
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
        # A second run would truncate the files under this one. The cursor file is replaced on every page, so the
        # lock needs its own file; the OS releases it when the process dies.
        self._lock = files.cursor.with_suffix(".lock").open("w")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            raise ScanError(f"{files.cursor.name} is in use by another run") from None
        on_disk = load_cursor(files.cursor)
        if on_disk is not None and on_disk != cursor:
            self._lock.close()
            raise ScanError(f"{files.cursor.name} changed while this run started; run it again")
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
        self._lock.close()


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
    needs_owner = {
        distinct_id
        for distinct_id, state in ch.items()
        if pg.get(distinct_id) is None or pg[distinct_id].person_uuid != state.winner_person_uuid
    }
    owners = sorted({ch[distinct_id].winner_person_uuid for distinct_id in needs_owner})
    owner_states = observe.pg_person_states(plan.team_id, owners) if plan.team_exists and owners else {}
    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for distinct_id, ch_state in ch.items():
        pg_row = pg.get(distinct_id)
        owner_state = (
            observe.person_pg_state(owner_states, ch_state.winner_person_uuid) if distinct_id in needs_owner else None
        )
        verdict = classify_mapping(pg_row, ch_state, ch_owner_pg_state=owner_state, team_exists=plan.team_exists)
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


def _load_key_set(paths: Sequence[Path]) -> np.ndarray:
    arrays = [np.fromfile(p, dtype="<u8") for p in paths if p.exists()]
    if not arrays:
        return np.empty(0, dtype="<u8")
    # Chunk key files never share keys, so an in-place sort is enough and peaks at half of np.unique's memory.
    keys = np.concatenate(arrays)
    keys.sort()
    return keys


def _contains(key_set: np.ndarray, keys: Sequence[int]) -> list[bool]:
    """Membership in a sorted key set, in O(len(keys) log len(key_set))."""
    if not keys or not len(key_set):
        return [False] * len(keys)
    wanted = np.asarray(keys, dtype="<u8")
    positions = np.minimum(np.searchsorted(key_set, wanted), len(key_set) - 1)
    return (key_set[positions] == wanted).tolist()


def _require_chunks_done(scan_dir: Path, plan: ScanPlan) -> list[RunFiles]:
    files = [chunk_files(scan_dir, i) for i in range(len(plan.chunks))]
    unfinished = [i for i, f in enumerate(files) if (c := load_cursor(f.cursor)) is None or c.phase != DONE]
    if unfinished:
        raise ScanError(f"chunks {unfinished} have not finished their ClickHouse phases")
    return files


def run_postgres(
    scan_dir: Path,
    *,
    resume: bool,
    id_range: IdRange | None = None,
    pause_seconds: float = 0.0,
    log: Callable[[str], None] = lambda _: None,
) -> Cursor:
    """List Postgres persons by id and report the persons and mappings no ClickHouse phase saw.

    `id_range` limits the run to Postgres person ids in [start, end), so several runs can split the team.
    """
    plan = load_plan(scan_dir)
    if not plan.team_exists:
        raise ScanError(f"team {plan.team_id} does not exist in Postgres; there is nothing to list")
    chunks = _require_chunks_done(scan_dir, plan)
    person_keys = _load_key_set([f.person_keys for f in chunks if f.person_keys is not None])
    mapping_keys = _load_key_set([f.mapping_keys for f in chunks if f.mapping_keys is not None])
    files = postgres_files(scan_dir, id_range)
    cursor = load_cursor(files.cursor)
    if cursor is not None and not resume:
        raise ScanError(f"{files.cursor} exists; pass resume to continue it")
    cursor = cursor or Cursor(phase="postgres", after=str(id_range.start - 1 if id_range else 0))
    before = id_range.end if id_range else None
    writer = _RunWriter(files, cursor)
    try:
        while cursor.phase != DONE:
            persons, next_after = list_persons_for_team(
                plan.team_id, int(cursor.after or 0), before_person_id=before, limit=plan.pg_page_size
            )
            if not persons:
                writer.finish_phase(DONE)
                break
            rows, counts = _classify_postgres_page(plan, persons, person_keys, mapping_keys)
            writer.commit(rows, counts=counts, after=str(persons[-1].id), phase="postgres")
            log(f"postgres: page {cursor.pages}, {len(persons)} persons, {len(rows)} reported")
            if next_after is None:
                writer.finish_phase(DONE)
            elif pause_seconds:
                time.sleep(pause_seconds)
    finally:
        writer.close()
    return cursor


def _classify_postgres_page(
    plan: ScanPlan, persons: Sequence[Any], person_keys: np.ndarray, mapping_keys: np.ndarray
) -> tuple[list[dict[str, Any]], Counter[str]]:
    observed_at = _now()
    team_id = plan.team_id
    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    uuids = [str(UUID(p.uuid)) for p in persons]
    seen = _contains(person_keys, [key_hash(u) for u in uuids])

    def pg_person(p: Any) -> PgPerson:
        return PgPerson(
            id=int(p.id), version=int(p.version), is_deleted=p.is_deleted, has_live_mappings=p.has_live_distinct_ids
        )

    unseen_live = [(p, u) for p, u, s in zip(persons, uuids, seen) if not s and not p.is_deleted]
    # The key sets decide which keys to read; ClickHouse itself decides whether a row exists.
    present = observe.ch_person_states(team_id, [u for _, u in unseen_live]) if unseen_live else {}
    for p, person_uuid in unseen_live:
        if person_uuid in present:
            counts["postgres/key_set_miss/person"] += 1
            continue
        verdict = classify_person(pg_person(p), None)
        counts[_count_key("person", verdict)] += 1
        rows.append(
            _row(
                kind="person",
                team_id=team_id,
                key=person_uuid,
                verdict=verdict,
                phase="postgres",
                observed_at=observed_at,
                pg=pg_person(p),
                ch=None,
            )
        )
    for p, person_uuid, s in zip(persons, uuids, seen):
        counts[f"postgres/person/{'deleted' if p.is_deleted else 'live'}"] += 1
        if s and not p.is_deleted and not p.has_live_distinct_ids:
            verdict = Verdict(flavor="no_live_mappings", sub_flavor=None, verb=PERSON_VERBS[("no_live_mappings", None)])
            counts[_count_key("person", verdict)] += 1
            rows.append(
                _row(
                    kind="person",
                    team_id=team_id,
                    key=person_uuid,
                    verdict=verdict,
                    phase="postgres",
                    observed_at=observed_at,
                    pg=pg_person(p),
                    ch=None,
                )
            )

    owners = {int(p.id): (p, u) for p, u in zip(persons, uuids) if p.has_live_distinct_ids}
    by_person = lookups._live_distinct_ids_for_persons(team_id, sorted(owners))
    mappings = [(owners[pid], did, version) for pid, dids in by_person.items() for did, version in dids]
    counts["postgres/mapping/live"] += len(mappings)
    mapping_seen = _contains(mapping_keys, [key_hash(did) for _, did, _ in mappings])
    unseen = [m for m, s in zip(mappings, mapping_seen) if not s]
    present_mappings = observe.ch_mapping_states(team_id, [did for _, did, _ in unseen]) if unseen else {}
    for (p, person_uuid), distinct_id, version in unseen:
        if distinct_id in present_mappings:
            counts["postgres/key_set_miss/mapping"] += 1
            continue
        pg_row = PgMapping(
            person_id=int(p.id),
            person_uuid=person_uuid,
            version=int(version),
            is_deleted=False,
            person_is_deleted=p.is_deleted,
        )
        verdict = classify_mapping(pg_row, None)
        counts[_count_key("mapping", verdict)] += 1
        rows.append(
            _row(
                kind="mapping",
                team_id=team_id,
                key=distinct_id,
                verdict=verdict,
                phase="postgres",
                observed_at=observed_at,
                pg=pg_row,
                ch=None,
            )
        )
    return rows, counts


@frozen
class ScanRuns:
    chunks: list[RunFiles]
    postgres: list[RunFiles]


def _run_files(scan_dir: Path, plan: ScanPlan) -> ScanRuns:
    chunks = [chunk_files(scan_dir, i) for i in range(len(plan.chunks))]
    postgres = [
        RunFiles(
            rows=p.with_name(p.name.replace(".cursor.json", ".rows.jsonl")),
            cursor=p,
            person_keys=None,
            mapping_keys=None,
        )
        for p in sorted(scan_dir.glob("postgres*.cursor.json"))
    ]
    return ScanRuns(chunks=chunks, postgres=postgres)


def _iter_rows(runs: Sequence[RunFiles]) -> Iterator[dict[str, Any]]:
    """Each run's rows up to its cursor: bytes after it are a page still being written, or one a resume redoes."""
    for run in runs:
        cursor = load_cursor(run.cursor)
        if cursor is None or not run.rows.exists():
            continue
        read = 0
        # Binary, so the count is in bytes like the cursor's offset; recorded offsets fall at line ends.
        with run.rows.open("rb") as handle:
            for line in handle:
                read += len(line)
                if read > cursor.rows_bytes:
                    break
                yield json.loads(line)


@frozen
class _Pair:
    old: str
    new: str


class _Groups:
    """Repair groups that span keys: a diverged mapping names its old owner (the ClickHouse one) and its
    new owner (the Postgres one). A pair is safe to repair as a unit only when neither person takes part
    in any other pair."""

    def __init__(self) -> None:
        self.new_by_old: defaultdict[str, set[str]] = defaultdict(set)
        self.old_by_new: defaultdict[str, set[str]] = defaultdict(set)
        self.person_verbs: dict[str, str | None] = {}
        self.primary_person_rows: set[str] = set()
        self.no_live_mapping_persons: set[str] = set()
        self.ghost_mapping_owners: set[str] = set()

    def observe(self, row: dict[str, Any]) -> None:
        if row["kind"] == "mapping" and row["flavor"] == "diverged" and row["sub_flavor"] in ("a_absent", "a_live"):
            old = row["evidence"]["ch"]["winner_person_uuid"]
            new = row["evidence"]["pg"]["person_uuid"]
            self.new_by_old[old].add(new)
            self.old_by_new[new].add(old)
        elif row["kind"] == "mapping" and row["flavor"] == "ghost" and row["sub_flavor"] == "owner_ghost":
            self.ghost_mapping_owners.add(row["evidence"]["ch"]["winner_person_uuid"])
        elif row["kind"] == "person":
            if row["flavor"] == "no_live_mappings":
                self.no_live_mapping_persons.add(row["key"])
            else:
                self.primary_person_rows.add(row["key"])
                if row["flavor"] == "ghost":
                    self.person_verbs[row["key"]] = row["verb"]

    def pair_for_old(self, old: str) -> _Pair | None:
        news = self.new_by_old.get(old)
        if not news or len(news) != 1:
            return None
        (new,) = news
        return _Pair(old=old, new=new) if self.old_by_new[new] == {old} else None

    def ambiguous(self, old: str) -> bool:
        return old in self.new_by_old and self.pair_for_old(old) is None

    def fold_mode(self, old: str) -> str:
        # A full fold restores the old person with its ghost mappings, then merges it with an event.
        # Without a ghost mapping there is no distinct id to merge from, so a light fold moves the data instead.
        return "full" if old in self.ghost_mapping_owners else "light"


def _regroup(row: dict[str, Any], groups: _Groups) -> dict[str, Any] | None:
    """Apply the cross-key decisions to one row. Returns None for a row merged into another."""
    kind, flavor, sub = row["kind"], row["flavor"], row["sub_flavor"]
    if kind == "person":
        key = row["key"]
        if flavor == "no_live_mappings" and key in groups.primary_person_rows:
            return None
        if flavor != "no_live_mappings" and key in groups.no_live_mapping_persons:
            row["also"] = ["no_live_mappings"]
        if flavor == "ghost":
            pair = groups.pair_for_old(key)
            if pair is not None:
                row["verb"], row["group"] = "fold", f"fold:{pair.old}>{pair.new}"
                row["fold_mode"] = groups.fold_mode(pair.old)
            elif groups.ambiguous(key):
                row["verb"], row["group"] = None, f"ambiguous:{key}"
            elif row["verb"] == "restore":
                row["group"] = f"restore:{key}"
        return row

    if flavor == "diverged" and sub in ("a_absent", "a_live"):
        old = row["evidence"]["ch"]["winner_person_uuid"]
        pair = groups.pair_for_old(old)
        if pair is None:
            new = row["evidence"]["pg"]["person_uuid"]
            row["sub_flavor"], row["verb"] = "ambiguous", None
            row["group"] = f"ambiguous:{new}" if len(groups.old_by_new[new]) > 1 else f"ambiguous:{old}"
        else:
            row["group"] = f"{row['verb']}:{pair.old}>{pair.new}"
            if row["verb"] == "fold":
                row["fold_mode"] = groups.fold_mode(pair.old)
    elif flavor == "ghost":
        owner = row["evidence"]["ch"]["winner_person_uuid"]
        if sub == "owner_ghost":
            pair = groups.pair_for_old(owner)
            if pair is not None:
                row["verb"], row["group"] = "fold", f"fold:{pair.old}>{pair.new}"
                row["fold_mode"] = groups.fold_mode(pair.old)
            elif groups.ambiguous(owner):
                row["verb"], row["group"] = None, f"ambiguous:{owner}"
            else:
                # A ghost mapping follows its ghost owner: restored with it, or left with it.
                row["verb"] = groups.person_verbs.get(owner)
                if row["verb"] == "restore":
                    row["group"] = f"restore:{owner}"
    return row


def _summary_group_name(team_id: int, group: str) -> str:
    # Group names embed person uuids; the summary keeps the verb and a hash, which report rows can be matched by.
    return f"{group.split(':', 1)[0]}:{hash_distinct_id(team_id, group)}"


def finalize(scan_dir: Path, *, partial: bool = False) -> dict[str, Any]:
    """Join every run's rows into the report, apply the cross-key groups, and write the summary."""
    plan = load_plan(scan_dir)
    runs_found = _run_files(scan_dir, plan)
    chunks, postgres = runs_found.chunks, runs_found.postgres
    cursors = {str(f.cursor.name): load_cursor(f.cursor) for f in [*chunks, *postgres]}
    unfinished = sorted(name for name, c in cursors.items() if c is None or c.phase != DONE)
    if plan.team_exists and not postgres:
        unfinished.append("postgres.cursor.json")
    complete = not unfinished
    if not complete and not partial:
        raise ScanError(f"unfinished runs: {unfinished}; finish them, or finalize a partial report")

    runs = [*chunks, *postgres]
    groups = _Groups()
    for row in _iter_rows(runs):
        groups.observe(row)

    reported: Counter[tuple[str, str, str | None, str | None]] = Counter()
    group_sizes: defaultdict[str, Counter[str]] = defaultdict(Counter)
    group_verbs: dict[str, str | None] = {}
    fold_modes: dict[str, str] = {}
    tmp = scan_dir / (REPORT_FILE + ".tmp")
    with tmp.open("w") as out:
        for row in _iter_rows(runs):
            final = _regroup(row, groups)
            if final is None:
                continue
            out.write(json.dumps(final, sort_keys=True) + "\n")
            reported[(final["kind"], final["flavor"], final["sub_flavor"], final["verb"])] += 1
            if final["group"] is not None:
                group_sizes[final["group"]][final["kind"]] += 1
                group_verbs[final["group"]] = final["verb"]
                if "fold_mode" in final:
                    fold_modes[final["group"]] = final["fold_mode"]
    os.replace(tmp, scan_dir / REPORT_FILE)

    classified: Counter[str] = Counter()
    for cursor in cursors.values():
        if cursor is not None:
            classified.update(cursor.counts)
    verbs: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for (kind, _, _, verb), n in reported.items():
        verbs[verb or "none"][f"{kind}_rows"] += n
    for verb in group_verbs.values():
        verbs[verb or "none"]["groups"] += 1
    largest = sorted(group_sizes.items(), key=lambda item: -sum(item[1].values()))[:25]
    summary = {
        "team_id": plan.team_id,
        "team_exists": plan.team_exists,
        "complete": complete,
        "unfinished_runs": unfinished,
        "finalized_at": _now(),
        # Chunk bounds are sampled keys, so the summary keeps only how many chunks the plan has.
        "plan": {**{k: v for k, v in plan.to_json().items() if k != "chunks"}, "chunks": len(plan.chunks)},
        "report": REPORT_FILE,
        # Postgres runs split by id range cover the team only if their ranges do; check them here.
        "postgres_runs": [f.cursor.name.removesuffix(".cursor.json") for f in postgres],
        "classified": dict(sorted(classified.items())),
        "reported": [
            {"kind": kind, "flavor": flavor, "sub_flavor": sub, "verb": verb, "rows": n}
            for (kind, flavor, sub, verb), n in sorted(reported.items(), key=lambda item: (-item[1], str(item[0])))
        ],
        "verbs": {verb: dict(c) for verb, c in sorted(verbs.items())},
        "groups": {
            "count": len(group_sizes),
            "fold_modes": dict(sorted(Counter(fold_modes.values()).items())),
            "largest": [
                {
                    "group": _summary_group_name(plan.team_id, group),
                    "verb": group_verbs[group],
                    "fold_mode": fold_modes.get(group),
                    "person_rows": c["person"],
                    "mapping_rows": c["mapping"],
                }
                for group, c in largest
            ],
        },
    }
    _write_json_atomic(scan_dir / SUMMARY_FILE, summary)
    return summary
