# Debugging Sessions for live_debugger

**Status:** Design — hackathon demo scope (not production-ready)
**Date:** 2026-05-14
**Product:** `products/live_debugger`

## Problem

Today `live_debugger` exposes `LiveDebuggerProgram` as the agent-facing unit:
the agent installs a hogtrace program, polls events, and installs another. The
flat list of programs in the database has no narrative — a human reviewing what
the agent did sees programs that appeared and disappeared but cannot tell in
what order, why each was installed, what was learned from it, or which captured
events mattered.

The goal is to make the agent's investigation legible. The agent works in a
session; everything it does — install, observe, reason, pin interesting events,
conclude — is appended to an ordered timeline humans can read after the fact.
The result is a Jupyter-notebook-like artifact, but read-only and produced
entirely by the agent.

## Scope

Hackathon demo. Optimize for "mostly works." Single-producer (one agent at a
time per session) is assumed; race-condition handling is intentionally minimal.

In scope:

- Storage for sessions + ordered entries + program → session FK
- Session-nested HTTP API + scoped MCP tools
- A simple notebook view rendering the timeline
- Updating the `instrumenting-with-hogtrace` agent skill to use sessions

Out of scope (call out, don't build):

- Concurrency hardening (locking, position fields, optimistic update)
- Reopening closed sessions
- Editing or deleting entries after creation
- Stale-session sweeping / TTL
- Pagination on the entries timeline (single-page list is fine for demo)
- Backfilling existing orphan programs into a synthetic session

## Architecture

Two new Postgres tables and one column on `LiveDebuggerProgram`.

```text
LiveDebuggerSession
  id              uuid pk
  team_id         fk posthog.Team (cascade)
  title           text
  description     text
  status          enum { open, closed }, default open
  created_at      timestamp
  closed_at       timestamp, nullable

LiveDebuggerSessionEntry
  id              uuid pk
  session_id      fk LiveDebuggerSession (cascade)
  kind            enum { note, program_install, program_uninstall,
                          event_highlight, conclusion }
  payload         jsonb        # shape depends on kind, validated per-kind
  created_at      timestamp

LiveDebuggerProgram
  ... existing fields ...
  session_id      fk LiveDebuggerSession (set null), nullable
```

Indexes:

- `LiveDebuggerSession (team_id, status)` — list active sessions per team.
- `LiveDebuggerSessionEntry (session_id, created_at)` — timeline reads.

`session_id` on `LiveDebuggerProgram` is nullable so existing orphan rows stay
valid. No backfill.

### Entry payload shapes

Each `kind` has a dedicated serializer. The viewset dispatches by `kind` and
validates the payload before insert.

```text
note               { markdown: str }
program_install    { program_id: uuid }
program_uninstall  { program_id: uuid }
event_highlight    { event_uuids: list[str], caption: str }
conclusion         { markdown: str }
```

`program_install` / `program_uninstall` entries are written by the server as a
side effect of the corresponding program endpoints; the agent does not write
them directly. `note`, `event_highlight`, `conclusion` are written directly by
the agent.

Entries are append-only. No PATCH, no DELETE.

### Session lifecycle

- `open` → `closed`. One-way. No reopening.
- `POST /sessions/{id}/close/` is atomic and does, in one transaction:
  1. Sets `status = closed`, `closed_at = now()`.
  2. If a `conclusion_markdown` is supplied, appends a `conclusion` entry.
  3. Sets `status = uninstalled` on every `LiveDebuggerProgram` belonging to
     the session that is currently `installed`. Already-uninstalled programs
     are left alone.
- Once closed, all write endpoints under the session 409 / 400.
- Multiple `open` sessions per team are allowed.

The libdebugger `/active` poller's wire response is built per-request from the
current set of `installed` programs, so it observes the post-close state on
its next poll.

## HTTP API

Routes live under the existing team-scoped router, alongside the current
`live_debugger_breakpoints` and `live_debugger_programs` viewsets.

```text
POST   /api/environments/:team_id/live_debugger_sessions/
GET    /api/environments/:team_id/live_debugger_sessions/
GET    /api/environments/:team_id/live_debugger_sessions/{id}/
POST   /api/environments/:team_id/live_debugger_sessions/{id}/close/

POST   /api/environments/:team_id/live_debugger_sessions/{id}/entries/
       body: { kind, payload }   # one of note / event_highlight / conclusion

POST   /api/environments/:team_id/live_debugger_sessions/{id}/programs/
       body: { code, description }
       effect: creates LiveDebuggerProgram (session_id=this) and a
               program_install entry, atomically

POST   /api/environments/:team_id/live_debugger_sessions/{id}/programs/{program_id}/uninstall/
       effect: transitions program to uninstalled and appends a
               program_uninstall entry, atomically

GET    /api/environments/:team_id/live_debugger_sessions/{id}/programs/{program_id}/events/
       proxies to existing program-events HogQL query
```

`GET /sessions/{id}/` returns the session row plus its full ordered entries
list inline (timeline reads are the common case; no separate entries
endpoint).

Existing top-level `LiveDebuggerProgramViewSet`:

- `list`, `retrieve`, `active` — unchanged.
- `create`, `uninstall` actions — left in place at the HTTP level (existing
  tests / clients keep working) but removed from the MCP surface so the agent
  cannot install probes outside a session.

Schema annotations: every new action gets `@extend_schema` with a typed
request + response serializer. Required for OpenAPI codegen → frontend types
and MCP tool scaffolding.

## MCP surface

`products/live_debugger/mcp/tools.yaml` — old program tools are disabled,
session tools take their place.

Disabled:

- `live-debugger-programs-install`
- `live-debugger-programs-uninstall`
- `live-debugger-programs-list`
- `live-debugger-programs-show`
- `live-debugger-programs-events`

Enabled (new):

- `debugging-session-start` — `live_debugger_sessions_create`
- `debugging-session-list` — `live_debugger_sessions_list`
- `debugging-session-show` — `live_debugger_sessions_retrieve` (timeline inline)
- `debugging-session-close` — `live_debugger_sessions_close_create`
- `debugging-session-add-entry` — `live_debugger_sessions_entries_create`
  (one tool, `kind` discriminator; the tool description spells out the three
  valid kinds and their payload shapes)
- `debugging-session-install-program` — `live_debugger_sessions_programs_create`
- `debugging-session-uninstall-program` — `live_debugger_sessions_programs_uninstall_create`
- `debugging-session-program-events` — `live_debugger_sessions_programs_events_retrieve`

Scopes reuse `live_debugger:read` / `live_debugger:write`. After editing
`tools.yaml`, regenerate via `hogli build:openapi` (the OpenAPI spec is the
input to MCP scaffolding).

## Frontend

New scenes:

- `/live-debugger/sessions/` — list of sessions for the team, most recent
  first. Each row: title, status pill, created/closed dates, link to detail.
- `/live-debugger/sessions/:id` — the notebook view. Header with title,
  description, status; below it the ordered entries rendered as a single
  vertical stack of cards.

Entry rendering (one renderer per kind, dispatched by `kind`):

- `note` — markdown.
- `program_install` — header line + a hogtrace source code block. Source is
  fetched from the linked `LiveDebuggerProgram` row.
- `program_uninstall` — single-line "Uninstalled program {id}".
- `event_highlight` — caption + a table of event payloads. Payloads are
  fetched via the existing program-events HogQL path, filtered to the entry's
  `event_uuids`. Missing UUIDs (not yet flushed to ClickHouse) are silently
  skipped.
- `conclusion` — markdown, rendered with a distinguishing border to mark the
  session's outcome.

Kea logic owns: fetching the session + timeline, fetching the linked program
code, fetching highlighted event payloads. Rendering components are
presentational.

A "Recent sessions" link is added to the existing `LiveDebugger` page header.

## Agent skill

`.agents/skills/instrumenting-with-hogtrace/SKILL.md` is rewritten around the
session workflow. The new flow the skill teaches:

1. Start a session with `debugging-session-start` describing the goal.
2. Install probes via `debugging-session-install-program`.
3. Read captured data via `debugging-session-program-events`.
4. Append observations / hypotheses via `debugging-session-add-entry` (kind
   `note`).
5. Pin informative events via `debugging-session-add-entry` (kind
   `event_highlight`).
6. Refine: install new programs, uninstall obsolete ones.
7. Close the session with a `conclusion`. Closing auto-uninstalls remaining
   programs.

The references (`language.md`, `patterns.md`, `troubleshooting.md`) are
content-stable except where they referenced the old install/uninstall tools.

## Testing

Backend (`products/live_debugger/backend/test_api.py`):

- Per-entry-kind: each valid payload round-trips; bad payloads return 400.
  Parameterized over `{note, event_highlight, conclusion}`.
- Session lifecycle:
  - Open session accepts entries.
  - Close transitions status and sets `closed_at`.
  - Close with `conclusion_markdown` appends a single `conclusion` entry.
  - Close auto-uninstalls every `installed` program in the session and leaves
    already-uninstalled ones alone.
  - Posting an entry or installing a program after close returns 4xx.
- Team isolation: cannot read or write entries in another team's session;
  cannot install a program into another team's session.
- `LiveDebuggerProgramViewSet.create` still works at the HTTP level (existing
  test stays green) but is not invoked by MCP.

Frontend (`liveDebuggerLogic.test.ts` + new tests):

- Session timeline fetch happy path.
- Entry rendering smoke test for each kind.

MCP:

- `hogli build:openapi` produces a clean spec.
- `pnpm --filter=@posthog/mcp run scaffold-yaml -- --sync-all` succeeds.
- Generated tool handlers compile.

## Implementation order

1. Models + migration (Session, SessionEntry, Program.session_id).
2. Backend viewset + serializers + tests.
3. `tools.yaml` updates + `hogli build:openapi` regen.
4. Frontend list view + notebook view + Kea logic.
5. Skill rewrite.
6. End-to-end smoke: start session → install → read events → highlight →
   close → view in UI.

## Risks / open items

- Concurrent appends to the same session aren't ordered deterministically
  beyond `created_at` resolution. Acceptable for single-producer agent;
  document as a known limitation, not a bug.
- Existing orphan programs (no `session_id`) won't appear in any session
  view. They remain reachable via the existing program endpoints. Demo
  audiences shouldn't be confused as long as the demo uses a fresh team.
- `event_highlight` doesn't validate event UUIDs at insert time. Rendering
  silently drops missing UUIDs. Trade-off: avoids flakiness against ClickHouse
  insertion lag.
