# Agent memory — architecture

A shared, editable, file-tree-based memory of markdown files that every PostHog agent
(the signals scout fleet, scouts, Slack-kicked-off agents) reads and writes per team.

## The memory tree

Each team has one tree of markdown files keyed by relative path:

- `project.md` — the single top-level project memory.
- `users/<slug>.md` — one file per human in the org.
- `scouts/<skill_name>/scratchpad.md` — per-scout scratchpads, living _inside_ the
  shared tree so any agent can read what a scout has learned.

Paths are normalized and validated (`logic.normalize_path`): relative only, no `..`,
markdown only. The tree is a convention, not a schema — agents can create other paths
under the same rules.

## Why object-storage-as-source-of-truth + a Postgres index

The bytes live in object storage at `agent_memory/{team_id}/{path}` (via the existing
`posthog/storage/object_storage.py` abstraction — SeaweedFS-first, no hardcoded
endpoints). A Postgres model `AgentMemoryFile` mirrors each file as a cached copy plus
metadata (`version`, `updated_by`, `updated_by_run`, timestamps), unique on
`(team, path)`.

This split buys three things a single store can't give alone:

1. **Fast reads and listing without S3 fan-out.** Listing a tree or reading one file is
   a single indexed Postgres query, not an `S3:ListObjects` + N `GetObject` calls.
2. **A transactional anchor for concurrency.** Optimistic concurrency needs a
   compare-and-set against a monotonic version under a row lock. Object storage has no
   transactions; Postgres does. The version bump and the content swap happen atomically
   in one transaction.
3. **A durable, browsable filesystem.** Object storage is the "live shared filesystem"
   surface: the same files are durable, exportable, and (future) directly mountable or
   git-syncable, independent of the app database.

Writes go to Postgres first (inside the transaction), then mirror the new body to object
storage. The mirror is best-effort and logged-on-failure: a transient storage hiccup
must not lose a row that already committed (the row _is_ a complete copy of the content),
and a later write repairs storage.

## Why compare-and-set beats last-write-wins

A fleet of agents edits the same tree concurrently. With naive last-write-wins, agent B
reading `project.md`, then agent A writing, then agent B writing back its stale copy
silently destroys A's change.

Compare-and-set closes that race: a writer supplies the `version` it last read.

- `expected_version=None` → "create"; succeeds only if the file doesn't exist.
- `expected_version=N` → "update a v N file"; succeeds only if the stored version is
  still N. A mismatch returns a conflict carrying the _actual_ stored version, and the
  caller must re-read, merge, and retry.

No write can overwrite a change it didn't see. The cost is that a caller occasionally has
to re-read and merge — which is exactly the work last-write-wins skips by losing data.

## Why section-append is the preferred agent mutation

Whole-file CAS is correct but coarse: if two agents touch _different_ sections of the
same file, one still has to lose the CAS race and retry, even though their edits don't
actually conflict.

`append_section(path, heading, body)` solves this. It reads-modifies-writes under a row
lock, upserting a single `## {heading}` section (replacing that heading's body if it
exists, appending it otherwise) and leaving every other section untouched. Two agents
editing different sections of the same file both succeed without a conflict, because the
serialized read-modify-write merges their changes section-by-section. This is why the MCP
`memory-append` tool and the facade `aappend_section` are documented as the default way
for an agent to record something — `memory-write` is reserved for genuine whole-file
rewrites.

## Layers

```text
MCP tools (memory-read/-write/-append/-list)   REST viewset (humans, Slack)
                         \                       /
                          presentation/views.py (DRF, thin)
                                    |
                          facade/api.py (async, the only cross-product surface)
                                    |
                              logic.py (CAS, append, path safety, storage mirror)
                          /                                   \
              Postgres: AgentMemoryFile                 object storage
              (index + cached copy + version)           (durable bytes, SoT)
```

- **Facade** (`facade/api.py`) exposes async functions — `aread_memory`,
  `awrite_memory` (CAS), `aappend_section`, `alist_memory`, `adelete_memory` — returning
  frozen `contracts` dataclasses. Other products import _only_ this (enforced by tach).
- **Logic** (`logic.py`) owns ORM queries, the CAS transaction, path validation, and the
  storage mirror. Team scoping is enforced via `TeamScopedRootMixin` + `team_scope()`.
- **Presentation** (`presentation/`) is a thin DRF surface: validate input, call the
  facade, map errors to HTTP (409 on version conflict, 404 on missing, 400 on bad path).

## Integrations

- **Signals scouts** — `products/signals/backend/scout_harness/memory_bridge.py` renders
  `project.md` + the scout's `scouts/<skill>/scratchpad.md` into the run prompt at start,
  and write-through-mirrors `SignalScratchpad` `remember` calls into the same scratchpad
  file. `SignalScratchpad` stays the authoritative store for the harness tools; the
  mirror is purely additive.
- **Slack / other agents** — reach memory through the same MCP tools (any agent whose
  team MCP token carries `agent_memory:read`/`:write`) and, in-process, through the
  facade.

## Future: git-backed merge (not built now)

The object-storage layout (`agent_memory/{team_id}/{path}`, one markdown file per path)
is deliberately git-shaped. A future iteration could back each team's tree with a real
git repository instead of (or alongside) object storage, which would give:

- true three-way merges for concurrent whole-file edits (instead of CAS-reject-and-retry),
- a full history / blame surface per file, and
- branch-per-agent-run workflows where a run's edits land on a branch and merge on
  success.

This is intentionally out of scope for the current implementation. CAS + section-append
already make concurrent edits safe; git backing is an enhancement to merge _ergonomics_,
not a correctness fix. When built, the facade contract (`aread`/`awrite`/`aappend`/
`alist`/`adelete`) should stay stable — only the storage layer behind `logic.py` changes.
