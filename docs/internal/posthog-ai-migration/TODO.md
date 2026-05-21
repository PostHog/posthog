# TODO — post-migration backfills

Things the migration intentionally drops or defers that we have to revisit before the new PostHog AI ships to non-internal users. Add new items at the bottom with date + owner.

---

## Billing context

**Dropped in:** `01_CONTEXT.md` § 2 (the row for `maxBillingContextLogic`).
**Status:** open.
**Owner:** _unassigned_.

### What we lost

Today `maxBillingContextLogic.tsx` resolves the org's subscription level, trial status, billing period, usage/limits, addons, and ships them as `MaxBillingContext` with every streaming request. Today's prompts (`ee/hogai/chat_agent/prompts/base.py`) reference billing-aware behavior — e.g. recommending upgrades, gating advice on plan, knowing when the user is near a quota.

The new spec drops this on the grounds that "system data injection already happens in the MCP" — i.e. billing data should reach the agent via tools, not via a prompt slice. That's the right *direction*, but the MCP tool side does not yet exist.

### What needs to land before flip

At least one of:

1. **A billing MCP tool.** New tool on the `posthog-data` (or new `posthog-billing`) MCP server exposing what `maxBillingContextLogic` resolves today: `get_billing_context(team_id)` returning subscription level, trial status, current period usage, limits, addons. The agent calls it when billing-relevant questions come up.
2. **A `billing` attachment type.** Auto-attached when the user is on a billing-adjacent scene (settings → billing, usage page). Renders in `<posthog_context>` as `Billing: pro plan, 12d into a 30d trial, 78% of monthly events quota used`. Trivial to implement once the wrapper template lands, but loses the "fetch only if relevant" benefit.
3. **Hybrid.** Auto-attach a one-line summary when the user is on a billing scene; expose the full picture as a tool the agent can call from anywhere.

Bias toward (1) — matches the architecture's "tools over prompts" direction and keeps the agent in control of token spend.

### Acceptance criteria

- The current prompt directives in `base.py` that depend on billing knowledge (recommend-upgrade, quota-aware advice) still produce the right behavior in evals. Without a billing source the agent will either fabricate billing assumptions or refuse to engage — both are regressions.
- The new tool / attachment respects team isolation (use `get_team()` in the serializer, never a request-scoped fallback).
- Eval snapshot tests cover: free plan, paid plan, trial, expired trial, over-quota.

### Cross-references

- `01_CONTEXT.md` § 2 (drop)
- `04_PROMPTS.md` (catalog of prompt segments that mention billing — confirm which become tool-driven vs deleted)

---

## Slash commands (SDK + MCP pairing)

**Dropped/deferred in:** `02_CORE.md` § 8 (sandbox-runtime disposition for the five existing commands).
**Status:** open.
**Owner:** _unassigned_.

### What we lost

The LangGraph runtime handled `/init`, `/remember`, `/usage`, `/feedback`, `/ticket` as inline prompt prefixes the graph picked up. The sandbox runtime currently treats `/init` and `/remember` as no-ops (with a "not supported yet" tooltip — see `02_CORE.md` § 8) and routes `/usage`, `/feedback`, `/ticket` to today's existing UI flows unchanged.

That's the minimum viable cut. The richer story — agent-initiated awareness ("you're near your quota — want shorter answers?") + a fast user-typed shortcut — needs SDK slash commands paired with MCP tools.

### What needs to land

For each command, decide MCP tool + SDK slash command, **frontend-only**, or skipped:

| Command | MCP tool | SDK slash command (`.claude/commands/posthog/*.md` baked into sandbox image) | Notes |
|---|---|---|---|
| `/init` | none | **Yes** — body expands to "Use the data tools to give me an overview of this project — top events, person properties, dashboards, group types, conventions." | Pure prompt expansion; uses existing `posthog-data` reads. No state writes since core memory is dropped. |
| `/remember [text]` | **Blocked** on the core-memory backfill story | **Blocked** | Today: hidden from autocomplete for sandbox runtime. Returns when memory does. |
| `/usage` | `posthog-billing.read_usage()` (intersects the billing-context backfill above) | **Yes** — body: "What's my PostHog AI credit usage this period?" | The MCP tool also unlocks agent-initiated awareness. Doubles as part of the billing TODO. |
| `/feedback [text]` | **Skip — frontend-only flow.** | **No SDK command** | Existing `FeedbackPrompt.tsx` modal collects text + rating. `slash-commands.tsx` keeps intercepting the command client-side, opens the modal, never reaches the agent. No agent involvement required; no MCP tool needed for parity with today. Revisit if a "submit my complaint about X in chat" UX becomes interesting. |
| `/ticket` | **Skip — frontend-only flow.** | **No SDK command** | Same as `/feedback` — `TicketPrompt.tsx` runs entirely in React. Today's gates (paid plan + idle conversation) stay in the frontend. |

### Mechanism reminder

- SDK slash commands ship as Markdown files baked into the sandbox image at the agent's commands directory (`.claude/commands/posthog/`). The agent-server CLI `--claudeCodeConfig` (cloud spec § 10.1) already accepts the directory path; no new infrastructure.
- The user types `/foo`, the frontend sends the literal "/foo" wrapped per `01_CONTEXT.md`, the agent SDK matches the command name and expands the body before the model sees it.
- New commands ship by editing the sandbox image, not the frontend.
- For `/feedback` and `/ticket` the frontend stops short and opens the existing React modal — no chat round-trip.

### Acceptance criteria

- `/init` produces a coherent "here's your project" summary in evals; matches today's tone and depth.
- `/usage` returns billing data via the new MCP tool and renders as a normal tool-call card; `slash-commands.tsx` autocomplete still suggests it.
- `/feedback` and `/ticket` modals open with the same fields and gating as today, regardless of `agent_runtime`.
- `/remember` shows the "not supported yet" tooltip until the memory backfill ships.

### Cross-references

- `02_CORE.md` § 8 (today's disposition matrix; revise once the SDK commands land)
- `01_CONTEXT.md` (commands are sent as normal user messages, wrapped in `<posthog_context>` like anything else)
- Billing-context TODO above (shared `posthog-billing.read_usage()` tool)

---

<!-- Add new TODOs below, in the same format. -->
