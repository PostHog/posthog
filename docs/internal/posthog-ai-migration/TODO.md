# TODO — post-migration backfills

Things the migration intentionally drops or defers that we have to revisit before the new PostHog AI ships to non-internal users. Add new items at the bottom with date + owner.

---

## Billing context

**Dropped in:** `01_CONTEXT.md` § 2 (the row for `maxBillingContextLogic`).
**Status:** open.
**Owner:** _unassigned_.

### What we lost

Today `maxBillingContextLogic.tsx` resolves the org's subscription level, trial status, billing period, usage/limits, addons, and ships them as `MaxBillingContext` with every streaming request. Today's prompts (`ee/hogai/chat_agent/prompts/base.py`) reference billing-aware behavior — e.g. recommending upgrades, gating advice on plan, knowing when the user is near a quota.

The new spec drops this on the grounds that "system data injection already happens in the MCP" — i.e. billing data should reach the agent via tools, not via a prompt slice. That's the right _direction_, but the MCP tool side does not yet exist.

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

| Command            | MCP tool                                                                       | SDK slash command (`.claude/commands/posthog/*.md` baked into sandbox image)                                                                                 | Notes                                                                                                                                                                                                                                                                                                                      |
| ------------------ | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/init`            | none                                                                           | **Yes** — body expands to "Use the data tools to give me an overview of this project — top events, person properties, dashboards, group types, conventions." | Pure prompt expansion; uses existing `posthog-data` reads. No state writes since core memory is dropped.                                                                                                                                                                                                                   |
| `/remember [text]` | **Blocked** on the core-memory backfill story                                  | **Blocked**                                                                                                                                                  | Today: hidden from autocomplete for sandbox runtime. Returns when memory does.                                                                                                                                                                                                                                             |
| `/usage`           | `posthog-billing.read_usage()` (intersects the billing-context backfill above) | **Yes** — body: "What's my PostHog AI credit usage this period?"                                                                                             | The MCP tool also unlocks agent-initiated awareness. Doubles as part of the billing TODO.                                                                                                                                                                                                                                  |
| `/feedback [text]` | **Skip — frontend-only flow.**                                                 | **No SDK command**                                                                                                                                           | Existing `FeedbackPrompt.tsx` modal collects text + rating. `slash-commands.tsx` keeps intercepting the command client-side, opens the modal, never reaches the agent. No agent involvement required; no MCP tool needed for parity with today. Revisit if a "submit my complaint about X in chat" UX becomes interesting. |
| `/ticket`          | **Skip — frontend-only flow.**                                                 | **No SDK command**                                                                                                                                           | Same as `/feedback` — `TicketPrompt.tsx` runs entirely in React. Today's gates (paid plan + idle conversation) stay in the frontend.                                                                                                                                                                                       |

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

## Web search tool placement

**Dropped/deferred in:** `04_PROMPTS.md` § 8 (resolved-deferred #10).
**Status:** open.
**Owner:** _unassigned_.

### What we lost

Today's LangGraph stack gates `web_search` behind "no Bedrock primary" — `toolkit.py:147-151` omits the tool whenever the team's LLM gateway routes to AWS Bedrock (Bedrock's Anthropic models don't expose Anthropic's hosted web search). For sandbox runs we currently include `web_search` unconditionally via the Claude Code SDK's built-in. Bedrock-routed teams will see a tool the model can't actually invoke — same regression we fixed in the LangGraph path.

### What needs to land

At Run-create, the `POST /sandbox/` handler inspects the LLM gateway routing for the user's team and:

1. **Bedrock route** — explicitly disable `web_search` on the Claude Code SDK invocation (the SDK accepts a tools allowlist/denylist; pass the denial for `WebSearch`).
2. **Anthropic route** — leave `web_search` enabled (the default).

The decision lives in the same code path that builds the system prompt and `--mcpServers` list (`build_posthog_ai_system_prompt` callsite / Task-create body construction). It needs read access to whichever signal `toolkit.py:147-151` reads today — confirm the gateway-routing accessor is callable from `ee/hogai/sandbox/`.

### Acceptance criteria

- Bedrock-routed team: tool not advertised to the model; the system prompt does not mention `web_search`.
- Anthropic-routed team: tool advertised + working end-to-end via the SDK built-in.
- No fallback path that calls `web_search` when it's been gated off (eval to confirm).

### Cross-references

- `04_PROMPTS.md` § 8 (#10) — original open question.
- `04_PROMPTS.md` § 5 (MCP tool surface) — web_search is not in the MCP catalog; it's a Claude built-in toggled at SDK init time.
- `toolkit.py:147-151` — the existing gating logic to mirror.

---

## MultiQuestionForm answer channel

**Dropped/deferred in:** `03_RICH_UI.md` § 10 (#4) and § 4 (`posthog-data.create_form` row).
**Status:** open.
**Owner:** _unassigned_.

### What we lost

Today the `create_form` tool renders a multi-question form in the input area; user answers come back via `UIPayloadAnswer.ui_payload.create_form.answers`. The LangGraph executor knows how to reconcile the answers with the in-flight tool call. In the sandbox runtime the agent-server has no equivalent backchannel — once the agent calls a tool, the protocol expects a tool-result event, not a "wait for the user to fill in something."

### What needs to land

Investigate whether the Claude Code SDK ships a built-in structured-question / form-asking tool:

1. **If yes** — map `create_form` onto it. Reuse the existing `MultiQuestionForm` UI for rendering and `MultiQuestionFormRecap` for the thread recap. Confirm the answer channel the SDK uses (likely a tool-result RPC the frontend posts via `POST /command/`) and wire `sandboxStreamLogic` to deliver answers as the in-flight tool's result.
2. **If no** — deprecate `create_form` for v1 of the sandbox runtime. The agent asks clarifying questions in plain text; users answer as their next message. This is a real UX regression for multi-question flows but is acceptable for v1.

### Acceptance criteria

- For path (1): submitting the form completes the `create_form` tool call as if the agent returned the answers itself; the next assistant turn sees them; the recap renders correctly when scrolled back.
- For path (2): the autocomplete suggestion for `create_form` is removed from the agent prompt; `MultiQuestionForm.tsx` and `MultiQuestionFormRecap.tsx` stay in the codebase (still used by LangGraph runtime) but are not mounted for sandbox conversations.

### Cross-references

- `03_RICH_UI.md` § 4 (`posthog-data.create_form` row) — table entry marked deferred.
- `03_RICH_UI.md` § 10 (#4) — original open question.

---

## Notebook block streaming

**Dropped/deferred in:** `03_RICH_UI.md` § 10 (#5) and § 4 (`posthog-notebook.create_notebook` row).
**Status:** open.
**Owner:** _unassigned_.

### What we lost

`NotebookArtifactAnswer` is built to render block-by-block as the model streams them — keeping the user engaged on long notebooks. For v1 of the sandbox runtime the `create_notebook` MCP tool returns the whole document on completion; we render in one shot. UX regression for long notebooks (multi-second wait with only a spinner).

### What needs to land

Pick a streaming channel and wire it into `posthog-notebook.create_notebook`:

1. **Preferred:** stream `DocumentBlock[]` partials as `tool_call_update.content` frames — standard ACP channel, no custom notification. `sandboxStreamLogic` accumulates frames as today; `NotebookArtifactAnswer` re-renders on each update.
2. **Alternative:** custom `_posthog/notebook_block` notification. Adds wire surface; only justified if the standard channel doesn't fit.

### Acceptance criteria

- Block-by-block render in the UI for notebooks > 3 blocks.
- No double-rendering when the final `rawOutput.blocks` arrives — content-dedup against accumulated partials.

### Cross-references

- `03_RICH_UI.md` § 4 (`posthog-notebook.create_notebook` row).
- `03_RICH_UI.md` § 10 (#5).

---

## Insight editor → Max "fix this query" trigger

**Dropped/deferred in:** `03_RICH_UI.md` § 10 (#7) and § 4 (`posthog-data.fix_hogql_query` row, dropped).
**Status:** open.
**Owner:** _unassigned_.

### What we lost

LangGraph exposed `fix_hogql_query` as a dedicated tool so the agent could repair a broken HogQL query in-conversation. In the sandbox runtime that tool is **gone** — there's no MCP equivalent. The user-facing flow needs to migrate from "agent fixes query as a tool call" to "user clicks a button in the insight editor → opens a Max conversation pre-filled with the broken query + error message."

### What needs to land

In the insight editor (wherever a HogQL syntax error surfaces — `frontend/src/scenes/insights/` query editor + ad-hoc HogQL editor surfaces), add an **"Ask Max to fix"** button next to the error display. Clicking it:

1. Captures the current query + error message.
2. Opens the Max side panel.
3. Starts a new conversation with a pre-filled user message:
   > Fix this HogQL query. Error: `<error>`. Query: `<query>`
4. Lets the agent respond using the standard `execute_sql` flow — agent corrects the query, runs it, returns results.

The pre-fill flow already has a precedent in the existing Max integration; reuse whatever `useMaxTool` / `openMaxWithPrompt` pattern exists for similar entry points (or extract a small helper if not).

### Acceptance criteria

- "Ask Max to fix" surfaces wherever a HogQL syntax error renders today (insight editor, ad-hoc query editor, SQL cell in notebooks).
- Clicking opens Max with a useful pre-filled prompt; the agent successfully corrects representative queries in evals.
- The button is hidden when `agent_runtime === 'langgraph'` (LangGraph still has the `fix_hogql_query` tool inline), or shown for both runtimes if simpler — confirm with the team.

### Cross-references

- `03_RICH_UI.md` § 4 (`posthog-data.fix_hogql_query` row — marked dropped).
- `03_RICH_UI.md` § 10 (#7).

---

## PostHog AI → PostHog Code integration

**Dropped/deferred in:** `04_PROMPTS.md` § 5.1 (the `TaskTool`, `CreateTaskTool`, `RunTaskTool`, `GetTaskRunTool`, `GetTaskRunLogsTool`, `ListTasksTool`, `ListTaskRunsTool`, `ListRepositoriesTool` rows); `03_RICH_UI.md` § 4.3; `MCP_TOOLS.md` "PostHog AI → PostHog Code integration".
**Status:** open.
**Owner:** _unassigned_.

### What we lost

Today's LangGraph stack ships an in-process tool family that lets PostHog AI drive PostHog Code:

- `TaskTool` / `CreateTaskTool` — create a coding task with a prompt and target repository.
- `RunTaskTool` / `GetTaskRunTool` / `GetTaskRunLogsTool` — kick off and monitor a run.
- `ListTasksTool` / `ListTaskRunsTool` / `ListRepositoriesTool` — discovery.

These tools manipulate `products/tasks/` Django models directly (not via MCP). The sandbox runtime exposes no equivalent — the agent literally cannot create a PostHog Code task from a Max conversation today. Gated by `has_phai_tasks` flag in the LangGraph stack, so impact is limited to teams that already have the integration on; but for those teams it's a real regression.

### Misconception to debunk

There is **no `posthog-code` MCP server**. PostHog Code is a _consumer_ of the same single-exec `posthog` MCP server in `services/mcp/`, identified by the `x-posthog-mcp-consumer: posthog-code` header. The earlier spec drafts that mentioned a "`posthog-code` MCP server" were wrong; this TODO is the corrected disposition.

### What needs to land

Add inner tools to the existing single-exec `posthog` server (`services/mcp/definitions/*.yaml`) that wrap the operations the legacy `TaskTool` family performs. Suggested inner-tool names (per the convention in `services/mcp/schema/tool-definitions-all.json`):

- `tasks-create` — wraps `CreateTaskTool`.
- `tasks-run` — wraps `RunTaskTool`.
- `tasks-get-run` — wraps `GetTaskRunTool`.
- `tasks-get-run-logs` — wraps `GetTaskRunLogsTool`.
- `tasks-list` / `tasks-list-runs` / `tasks-list-repositories` — wraps the three list tools.

Each gets:

1. A YAML entry in `services/mcp/definitions/` with `enabled: true` and the matching `operation:` ID against the OpenAPI schema.
2. A serializer + viewset on the Django side if one doesn't exist (`products/tasks/backend/`).
3. A `posthog-ai-sandbox-tool-tasks-{slug}` flag for per-tool rollout (mirrors the per-tool flag pattern in `00_OVERVIEW.md` § 9).

### Renderers

The fallback card handles all seven shapes — every operation either returns a URL (CTA) or a text list. Custom adapters only become worthwhile if user behavior shows Max-driven Code-task creation is a common workflow.

### Acceptance criteria

- Sandbox conversations on teams with `has_phai_tasks` can create, run, and read PostHog Code tasks from chat, matching today's LangGraph UX.
- Per-inner-tool rollout flags wired up.
- Eval coverage for "user asks Max to ship a small fix" → agent calls `tasks-create` + reports back with the URL.

### Cross-references

- `04_PROMPTS.md` § 5.1 (the `TaskTool` family rows now point here).
- `03_RICH_UI.md` § 4.3 (notes that PostHog Code integration is not a separate server; routes here).
- `MCP_TOOLS.md` "PostHog AI → PostHog Code integration" (shape table for the future inner tools).
- `00_OVERVIEW.md` § 9 MCP-B (rollout slot reserved for this work).

---

<!-- Add new TODOs below, in the same format. -->
