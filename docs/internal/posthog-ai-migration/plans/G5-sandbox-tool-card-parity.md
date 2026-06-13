# Sandbox tool-call card parity: built-in tool display mapping + \_meta.claudeCode.\* consumption + code-diff rendering

> **Source:** outstanding*items.md § 5 (Item 5 / § 8 code diffs) + § 8 "\_meta.claudeCode.*" + § 8 "Claude built-in tool display mapping" · **Locus:** frontend — tool-call card rendering
> **Effort:** M (core S–M + a deferred sub-task) · **Priority:** Medium-high · **Blocks rollout:** No
> **Joins:** Three § 8 / Item-5 gaps that all live in the tool-call CARD layer — built-in display mapping (`mcpToolRegistry.tsx`), `\_meta.claudeCode._` consumption (`sandboxWireTypes.ts`+`resolveToolKey` + ingest), and code-diff rendering (`extractors.ts`+ a new diff widget). They share`resolveToolKey`, the `tool_call`/`tool_call_update`ingest path, the`ToolInvocation`/`McpToolCallMessage`shapes, the registry, and`FallbackMcpToolRenderer`, so one engineer touching that chain can land them as a single coherent pass without re-reading the same code three times. The diff sub-task is conditional on a producer existing — see Decisions.

## Problem

Three independent defects degrade how the sandbox runtime renders agent tool calls. All three sit in the same render chain, and the first two are coupled by a single root cause.

1. **Claude built-in tools render with raw, useless headers and a default wrench icon.** When the agent calls a Claude built-in (`Edit`, `Write`, `Read`, `Grep`, `Glob`, `LS`, `Bash`, `Task`, `TaskCreate`/`TaskUpdate`/`TaskGet`/`TaskList`, `WebSearch`, `WebFetch`, `NotebookEdit`/`NotebookRead`, `ExitPlanMode`, `AskUserQuestion`, and the SDK's `TodoWrite`/`ToolSearch`/`Skill` family), the card falls through to `FallbackMcpToolRenderer` with the wire name and a generic icon. There is no friendly title or icon mapping for built-ins in `mcpToolRegistry.tsx`.

2. **`_meta.claudeCode.*` is emitted by the agent but silently dropped — a latent correctness bug.** Twig stamps every Claude tool frame with `_meta.claudeCode.toolName` (the stable SDK tool name, e.g. `"Edit"`, `"TodoWrite"`) and, on a permission denial, `_meta.claudeCode.toolResponse.{decisionReason, decisionReasonType, message}`. PostHog's `SessionUpdateToolCallMeta` type declares a **flat snake_case** shape (`decision_reason`, `decision_reason_type`, `message`) that does not match the wire, and `resolveToolKey` never reads `_meta` at all (zero references repo-wide). Effects: (a) built-in tool cards can never key on their real tool name (problem 1 cannot be fully fixed without this), (b) permission denials render as a generic failure with the reason text dropped, and (c) MCP approval cards cannot name the server + inner tool.

3. **No diff UI for edit-shaped tool calls.** Twig emits `Edit`/`Write`/`NotebookEdit` content as a pre-built diff content block `{ type: "diff", path, oldText, newText }`. PostHog has no extractor or widget that recognizes it; it falls through `contentBlockText` to `JSON.stringify`, so the user sees a raw blob instead of a diff. **However, PostHog AI is no-repo** (the gaps doc calls out its "no-repo, no-desktop posture") — classic file edits are near-zero, so this sub-task is conditional on identifying a real producer (see Decisions).

## Current behavior (verified)

All citations confirmed by reading the files on 2026-06-13. Note: the source doc cites `frontend/src/scenes/max/sandboxWireTypes.ts`, but the real path is `frontend/src/scenes/max/types/sandboxWireTypes.ts`.

### The ingest → resolve → render chain

- **`tool_call` ingest:** `frontend/src/scenes/max/sandboxStreamLogic.ts:939-963`. Reads `rawServerName = update.serverName ?? 'posthog'` and `rawToolName = update.toolName ?? update.title ?? ''`, calls `resolveToolKey(...)`, and folds the result into a `ToolInvocation`. It does **not** read `update._meta`.
- **`tool_call_update` ingest:** `sandboxStreamLogic.ts:964-1031`. Re-resolves the key from accumulated `rawInput`, merges content/status/error. Also does **not** read `update._meta`.
- **`resolveToolKey`:** `sandboxStreamLogic.ts:112-147` (doc cited ~112-147 — accurate). For a non-`exec` tool it returns `{ resolvedKey: toolName }`. For built-ins the wire carries **no** `toolName` field (see below), so `toolName` is empty, `rawToolName` falls back to `update.title`, and `resolvedKey` becomes the human title string (e.g. `"Edit \`foo.ts\`"`) — which can never match a registry key.
- **`McpToolCallMessage` assembly:** `frontend/src/scenes/max/Thread.tsx:122-144` (`toolInvocationToMessage`). The card is selected at `Thread.tsx:179` via `lookupMcpToolRenderer(message.resolvedKey)`.
- **Fallback card:** `frontend/src/scenes/max/messages/FallbackMcpToolRenderer.tsx:48-108`. Header is `message.title || message.innerToolName || message.rawToolName || 'Tool call'` (so built-ins already show Twig's title in the header — but with a wrench icon and no semantic treatment). Failed state renders `message.error?.message` as plain danger text (`:66-68`). The doc's "~75-100" cite points at the `LemonCollapse` panels; accurate.
- **Registry:** `frontend/src/scenes/max/mcpToolRegistry.tsx`. Entries register data-tool widgets keyed by inner tool name; `lookupMcpToolRenderer` (`:154-163`) falls back to `{ displayName: resolvedKey, icon: <IconWrench/>, Renderer: FallbackMcpToolRenderer }`. No built-in entries exist.
- **`SessionUpdateToolCallMeta`:** `frontend/src/scenes/max/types/sandboxWireTypes.ts:141-145` (doc cited ~141-145 — accurate). Declares flat `decision_reason?`, `decision_reason_type?`, `message?`. Referenced only by `SessionUpdateToolCallUpdate._meta` at `:159`. Never read at runtime.
- **Crash error path** (sibling-plan territory): `sandboxStreamLogic.ts:887-891` (`_posthog/error` → `pushErrorItem`). The doc's "crash error ~:677" now lives at `:889`; line 677 today is the `task_run_state` terminal handler. This belongs to **G7**, not this plane — do not touch it here.

### The real Twig wire shape (confirmed)

- **`ToolUpdateMeta` type** — `Twig/packages/agent/src/adapters/claude/types.ts:130-140`:

  ```ts
  export type ToolUpdateMeta = {
    claudeCode?: { toolName: string; toolResponse?: unknown; parentToolCallId?: string; bashCommand?: string }
    terminal_info?: TerminalInfo
    terminal_output?: TerminalOutput
    terminal_exit?: TerminalExit
  }
  ```

- **Every tool_call frame stamps `_meta.claudeCode.toolName`** with the SDK tool name — `Twig/packages/agent/src/adapters/claude/conversion/sdk-to-acp.ts:252-281` (`...toolMeta(chunk.name, ...)`, builder at `:118-129`). The frame body is `{ _meta, toolCallId, sessionUpdate, rawInput, status, ...toolInfo }` where `toolInfo` (from `toolInfoFromToolUse`) contributes only `title`, `kind`, `content`, `locations` — **there is no top-level `toolName` field for built-ins.** That is why `resolveToolKey` currently gets an empty `toolName`.
- **Permission denial** — `Twig/.../conversion/sdk-to-acp.ts:796-822` (doc cited ~810-818 — the `toolResponse.*` block; accurate). A `permission_denied` SDK message emits a `tool_call_update` with `status: "failed"`, a `Permission denied: <reason>` text content block, and:

  ```ts
  _meta: { claudeCode: { toolName: message.tool_name, toolResponse: { decisionReasonType, decisionReason, message } } }
  ```

- **Inline `canUseTool` denial** — `Twig/packages/agent/src/adapters/claude/permissions/permission-handlers.ts:68-96` (doc cited ~59-68 — that range is the `ToolHandlerContext` interface; the actual `emitToolDenial`/`buildDenialResult` are at `:68-96`). This path emits a `tool_call_update` with `status: "failed"` and a text content block (`User refused permission…`) but **no `_meta`** — so the denial-reason renderer must tolerate a missing `_meta` and fall back to the content text / `error.message`.
- **Built-in titles/kinds** are computed by `Twig/.../conversion/tool-use-to-acp.ts:55-456` (`toolInfoFromToolUse`). Examples: `Edit` → `Edit \`path\``, kind`edit`, content`[{type:"diff",path,oldText,newText}]`;`Read`→`Read <path> (range)`, kind`read`;`Grep`→ reconstructed`grep …`command line, kind`search`;`Task`/`Agent`→`input.description`, kind`think`;`WebSearch`/`WebFetch`→ kind`fetch`. Twig's built-in tool **name sets** are in`Twig/packages/agent/src/adapters/claude/tools.ts:11-37`:`READ_TOOLS = {Read, NotebookRead}`,`WRITE_TOOLS = {Edit, Write, NotebookEdit}`,`BASH_TOOLS = {Bash, BashOutput, KillShell}`,`SEARCH_TOOLS = {Glob, Grep, LS}`,`WEB_TOOLS = {WebSearch, WebFetch}`,`AGENT_TOOLS = {Task, Agent, TaskCreate, TaskUpdate, TaskGet, TaskList}`.
- **Diff content block shape** — `Twig/packages/agent/src/utils/acp-content.ts:46-47`: `{ type: "diff", path, oldText, newText }`, pushed **directly** into `content[]` (not wrapped in the `{type:"content",content:{...}}` envelope that text/image blocks use). So a diff arrives in `ToolInvocation.contentBlocks` as a flat `type: "diff"` object, and `contentBlockText` (`extractors`-adjacent, in `FallbackMcpToolRenderer.tsx:14-26`) currently `JSON.stringify`s it.

### What renders the wire `toolName` test today

`sandboxStreamLogic.test.ts:124-125` already asserts `resolveToolKey('claude', 'TodoWrite', {}).resolvedKey === 'TodoWrite'`, and `:294` feeds a `tool_call` with `toolName: 'ToolSearch'`. These tests pass because they synthesize a `toolName` the **real wire does not send for built-ins**. They document the intended contract but not Twig's actual behavior — the new tests must cover the empty-`toolName` + `_meta.claudeCode.toolName`-present case.

## Approach

### Sub-task A — fix the `_meta` type, then read it (root-cause fix; ship first)

1. **Replace the flat `SessionUpdateToolCallMeta`** in `types/sandboxWireTypes.ts:141-145` with the real nested shape, mirroring Twig's `ToolUpdateMeta`:

   ```ts
   export interface SessionUpdateClaudeCodeMeta {
     toolName?: string
     /** Present on a permission denial; free-form on other frames. */
     toolResponse?: { decisionReason?: string; decisionReasonType?: string; message?: string } | unknown
     parentToolCallId?: string
     bashCommand?: string
   }
   export interface SessionUpdateToolCallMeta {
     claudeCode?: SessionUpdateClaudeCodeMeta
   }
   ```

   Add `_meta?: SessionUpdateToolCallMeta` to `SessionUpdateToolCall` (`:126-138`) too — Twig stamps it on the initial `tool_call`, not only on updates. Keep the module's "typed, not validated" contract: every read stays runtime-guarded.

2. **Thread the SDK tool name through `resolveToolKey`.** Add an optional `meta` parameter so the resolver can prefer the stable SDK name over the title fallback for built-ins:

   ```ts
   export function resolveToolKey(
     serverName: string,
     toolName: string,
     input: Record<string, unknown>,
     claudeToolName?: string
   ): ResolvedToolKey
   ```

   The `exec` branch is unchanged. The final `return { resolvedKey: toolName }` becomes `return { resolvedKey: toolName || claudeToolName || '' }` — so when the wire `toolName` is empty (every built-in), the key is the SDK name (`"Edit"`, `"TodoWrite"`, …) instead of the human title. Update both call sites (`:947` tool_call, `:990` tool_call_update re-resolve) to pass `extractClaudeToolName(update._meta)`. Add a small guarded helper `extractClaudeToolName(meta: unknown): string | undefined`.

   **Also persist the SDK name on `ToolInvocation`** (new optional field `claudeToolName?: string` in `types/sandboxStreamTypes.ts`) so renderers and the denial path can read it without re-parsing. Flow it through `toolInvocationToMessage` (`Thread.tsx:129-143`) onto `McpToolCallMessage` (new optional field in `maxTypes.ts:245-264`).

3. **Read the denial reason.** In the `tool_call_update` ingest (`:992-1008`), when `status === 'failed'`, extract `decisionReason ?? message` from `_meta.claudeCode.toolResponse` and prefer it for the `error.message` when the update carries no explicit `error`. The renderer (FallbackMcpToolRenderer or a thin denial treatment) then shows the real reason; when `_meta` is absent (the inline `canUseTool` path), it falls back to the content text / existing `error.message` — so no regression for that path.

4. **Approval-card server + inner-tool naming.** `parsePermissionRequestFrame` (`:213-258`) already resolves a key from `toolCall.serverName`/`toolCall.toolName`. Where the permission frame's `toolCall` carries `_meta.claudeCode.toolName` (MCP approvals — gaps doc § 3.3, Twig `e0ddd01e`), pass it into `resolveToolKey` so the card names the inner tool. This is a small additive change; if no permission frame in PHAI carries `_meta` today, it is a no-op and harmless (verify against a captured frame — see Open questions).

### Sub-task B — built-in display mapping (registry entries)

Register friendly title/icon entries in `mcpToolRegistry.tsx` keyed by the **stable SDK tool name** (now reachable via sub-task A). Reuse the existing `FallbackMcpToolRenderer` as the `Renderer` for all of them — the goal is title + icon, not bespoke widgets — except `Edit`/`Write`/`NotebookEdit`, which point at the new diff widget **only if** sub-task C ships (otherwise they also use the fallback). The fallback header already prefers `message.title`, so Twig's rich titles (`Edit \`foo.ts\``,`grep …`) keep flowing through; the registry contributes the icon and a stable`displayName` for any tool whose title is empty.

Mapping (icons verified against `@posthog/icons@0.36.6` `dist/src/Icons.d.ts` — **all present EXCEPT `IconRobot`**, which is not in `@posthog/icons`; it lives only in the legacy `lib/lemon-ui/icons` set (`icons.tsx:1212`) and is already imported from there in `max-constants.tsx`. Source `IconRobot` from `lib/lemon-ui/icons` with a separate import, or substitute an `@posthog/icons` alternative — do **not** add it to the existing `@posthog/icons` import block in `mcpToolRegistry.tsx` or the build breaks):

| SDK tool name(s)                                               | displayName | icon                                                             |
| -------------------------------------------------------------- | ----------- | ---------------------------------------------------------------- |
| `Read`, `NotebookRead`                                         | Read        | `IconEye`                                                        |
| `Edit`, `Write`, `NotebookEdit`, `MultiEdit`                   | Edit        | `IconPencil`                                                     |
| `Grep`, `Glob`, `LS`                                           | Search      | `IconSearch`                                                     |
| `Bash`, `BashOutput`, `KillShell`                              | Terminal    | `IconTerminal`                                                   |
| `WebSearch`, `WebFetch`                                        | Web         | `IconGlobe`                                                      |
| `Task`, `Agent`                                                | Subagent    | `IconRobot` (⚠️ from `lib/lemon-ui/icons`, not `@posthog/icons`) |
| `TaskCreate`, `TaskUpdate`, `TaskGet`, `TaskList`, `TodoWrite` | Tasks       | `IconListCheck`                                                  |
| `Skill`                                                        | Skill       | `IconMagicWand`                                                  |
| `ToolSearch`                                                   | Tool search | `IconSearch`                                                     |
| `ExitPlanMode`                                                 | Plan        | `IconDocument`                                                   |
| `AskUserQuestion`                                              | Question    | `IconAI`                                                         |

Add these as `for (const key of [...])` loops mirroring the existing data-tool registration blocks. Confirm `MultiEdit` and `Skill` are actually live SDK tool names in the pinned agent SDK before relying on them (they appear in upstream Claude SDKs but Twig's `tools.ts` does not enumerate them) — register them speculatively; they cost nothing if never emitted.

### Sub-task C — code-diff rendering (CONDITIONAL — default: deferred-until-producer)

The mechanism is cheap because the diff content block arrives pre-built. Plan it but gate it on a producer:

- Add `extractDiffBlocks(message)` to `extractors.ts` that scans `message.content` for flat `{ type: 'diff', path, oldText, newText }` blocks (and tolerates the `{type:'content',content:{type:'diff',...}}` envelope just in case).
- Add a `DiffWidget` adapter that renders each block via the existing `MonacoDiffEditor` (`frontend/src/lib/components/MonacoDiffEditor.tsx` — `original`/`modified` props, auto-height, read-only, already used in `ActivityLog`). Language inferred from the file extension; fall back to plaintext. For a lightweight alternative if Monaco's bundle weight is a concern in the Max thread, a line-diff using the existing `CodeSnippet` is acceptable, but Monaco is already loaded elsewhere and gives syntax highlighting for free.
- Register `Edit`/`Write`/`NotebookEdit`/`MultiEdit` → `DiffWidget` in the registry (replacing the fallback entries from sub-task B for those keys), with the widget itself falling back to the fallback card when no diff block is present.

**Default recommendation: do NOT build C in this pass.** PHAI is no-repo, so `Edit`/`Write` are near-zero today. Mark C **deferred-until-producer** and ship A + B as the core. Revisit when a concrete diff producer lands (see Open questions for candidates: `notebook-edit` and `insight-update` are the realistic ones, but neither emits the `{type:'diff'}` block today — they return REST payloads handled by `CreateNotebookWidget`/`CreateInsightWidget`).

## Implementation steps

1. **Type fix (A.1):** rewrite `SessionUpdateToolCallMeta` to the nested `claudeCode` shape in `types/sandboxWireTypes.ts`; add `_meta?` to `SessionUpdateToolCall`. Add `extractClaudeToolName` + a denial-reason helper (or inline guards).
2. **Resolver + ingest (A.2/A.3):** extend `resolveToolKey` with the optional `claudeToolName` arg and the `toolName || claudeToolName` fallback; pass it at both ingest call sites; persist `claudeToolName` on `ToolInvocation`; extract denial reason on failed `tool_call_update`.
3. **Plumb through (A.2):** add `claudeToolName?` to `ToolInvocation` (`sandboxStreamTypes.ts`) and `McpToolCallMessage` (`maxTypes.ts`); flow it in `toolInvocationToMessage` (`Thread.tsx`).
4. **Approval naming (A.4):** thread `_meta.claudeCode.toolName` into `parsePermissionRequestFrame`'s `resolveToolKey` call (no-op-safe).
5. **Registry (B):** add built-in title/icon entries in `mcpToolRegistry.tsx` keyed by SDK name, all using `FallbackMcpToolRenderer`.
6. **(Deferred) Diff (C):** only if a producer is confirmed — `extractDiffBlocks`, `DiffWidget`, registry re-point for edit tools.
7. **Tests** (see Testing) and lint/typecheck.

Sub-task A is a hard prerequisite for B (the registry key is the SDK name, only reachable after A). C is independent and deferred.

## Files to change

| Path                                                                    | Change                                                                                                                                                                                                                                                                                                                                                            |
| ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frontend/src/scenes/max/types/sandboxWireTypes.ts`                     | Replace flat `SessionUpdateToolCallMeta` (`:141-145`) with nested `claudeCode` shape; add `_meta?` to `SessionUpdateToolCall` (`:126-138`).                                                                                                                                                                                                                       |
| `frontend/src/scenes/max/sandboxStreamLogic.ts`                         | Extend `resolveToolKey` (`:112-147`) with optional `claudeToolName`; add `extractClaudeToolName` + denial-reason guard; pass meta at tool_call ingest (`:947`) and tool_call_update re-resolve (`:990`); set `error.message` from `toolResponse.decisionReason` on failed updates; persist `claudeToolName`; pass meta in `parsePermissionRequestFrame` (`:235`). |
| `frontend/src/scenes/max/types/sandboxStreamTypes.ts`                   | Add `claudeToolName?: string` to `ToolInvocation`.                                                                                                                                                                                                                                                                                                                |
| `frontend/src/scenes/max/maxTypes.ts`                                   | Add `claudeToolName?: string` to `McpToolCallMessage` (`:245-264`).                                                                                                                                                                                                                                                                                               |
| `frontend/src/scenes/max/Thread.tsx`                                    | Flow `claudeToolName` through `toolInvocationToMessage` (`:122-144`).                                                                                                                                                                                                                                                                                             |
| `frontend/src/scenes/max/mcpToolRegistry.tsx`                           | Register built-in title/icon entries keyed by SDK name.                                                                                                                                                                                                                                                                                                           |
| _(deferred)_ `frontend/src/scenes/max/messages/adapters/extractors.ts`  | Add `extractDiffBlocks`.                                                                                                                                                                                                                                                                                                                                          |
| _(deferred)_ `frontend/src/scenes/max/messages/adapters/DiffWidget.tsx` | New diff adapter (Monaco).                                                                                                                                                                                                                                                                                                                                        |
| Test files (all already exist)                                          | `sandboxStreamLogic.test.ts`, `mcpToolRegistry.test.tsx`, `sandboxWireTypes.test.ts`, `FallbackMcpToolRenderer.test.ts`, `extractors.test.ts`.                                                                                                                                                                                                                    |

No backend / serializer / `lib/api` changes — purely frontend wire-shape and render logic. The `/adopting-generated-api-types` skill does **not** apply (no `lib/api` types touched). The `/using-kea-disposables` skill does not apply (no new timers/listeners). No DRF skill applies.

## Decisions & open questions

1. **Ship C (diffs) now, or defer?** — **Recommend DEFER (deferred-until-producer).** PHAI is no-repo; `Edit`/`Write` are near-zero. Land A + B as the shippable core; document the C design (above) so it's a half-day add when a producer appears.
2. **What is the real diff producer in PHAI, if any?** — Verified today: none emits a `{type:'diff'}` block. `notebook-edit` and `insight-update` are the only edit-shaped PHAI tools, and both return REST payloads rendered by existing widgets (`CreateNotebookWidget`/`CreateInsightWidget`), not diff blocks. **Recommendation:** keep C deferred until a notebook-block-edit or insight-diff producer is explicitly added (cross-reference TODO.md "notebook block streaming"). If product wants visible before/after on notebook edits, that's a producer change first, renderer second.
3. **`Renderer` for built-ins: fallback vs bespoke?** — **Recommend `FallbackMcpToolRenderer` for all built-ins.** The fallback header already shows Twig's rich title; the registry only needs to supply the icon + stable `displayName`. Bespoke widgets are unjustified for no-repo data conversations.
4. **Denial UX: dedicated card vs enrich the fallback's failed state?** — **Recommend enriching the fallback's failed-state block** (`FallbackMcpToolRenderer.tsx:66-68`) to show the decision reason when present. A dedicated `ToolDenialRenderer` is over-engineering for the current volume; revisit only if denials become common.
5. **Does any PHAI permission frame carry `_meta.claudeCode.toolName` today?** — Must verify against a captured `_posthog/permission_request` log entry. The gaps doc (§ 3.3, Twig `e0ddd01e`) says MCP-tool approvals do. **Recommendation:** make the `parsePermissionRequestFrame` read additive and no-op-safe so it's correct whether or not the field is present; do not block on this.
6. **Speculative built-in names (`MultiEdit`, `Skill`):** not enumerated in Twig's `tools.ts`. **Recommend registering them anyway** — zero cost if never emitted, future-proof if the SDK starts sending them.

## Dependencies & sequencing

- **Within this pass:** A → B (B's registry keys are only reachable after A reads `_meta.claudeCode.toolName`). C is independent and deferred. Do A first, then B, in one PR.
- **G7 (`G7-sandbox-streaming-resilience.md`):** owns the crash affordance / `_posthog/error` path (`sandboxStreamLogic.ts:887-891`, the doc's stale "crash error ~:677"). Do **not** touch error/crash rendering here — only the per-tool denial reason on failed `tool_call_update`s.
- **G6 (`G6-sandbox-notification-rendering.md`):** owns the dropped `_posthog/*` notifications (resources_used bar, usage/status/compaction/task/sdk). This pass touches only `session/update` tool frames, not the `_posthog/*` dispatch at `sandboxStreamLogic.ts:914`. No overlap; coordinate only if both edit the `ingestAcpFrame` switch in the same window.
- No backend/serializer dependency; ships independently of G1–G4, G8, G9.

## Testing

All target test files already exist — extend them (jest, single top-level `describe` per file, parameterized where variations repeat).

- **`sandboxWireTypes.test.ts`** — assert the nested `_meta.claudeCode.*` shape parses and the discriminant guards still hold. **This file already encodes the OLD flat shape and will break on the type rewrite:** the fixture at `:172-176` builds `_meta: { decision_reason, decision_reason_type, message }` and the test at `:297-306` asserts `body._meta?.decision_reason`. Both must be rewritten to the nested `_meta.claudeCode.toolResponse.decisionReason` shape (not merely extended) — this is the compile gate that proves the type change landed.
- **`sandboxStreamLogic.test.ts`** — the load-bearing cases:
  - A built-in `tool_call` with **empty `toolName`** + `_meta.claudeCode.toolName: "Edit"` resolves to `resolvedKey: "Edit"` (the regression the current `:124-125` test masks by synthesizing a `toolName`). Parameterize across `Edit`/`TodoWrite`/`Grep`/`Task`.
  - A failed `tool_call_update` with `_meta.claudeCode.toolResponse.decisionReason` surfaces that reason on `error.message`.
  - The inline-denial path (failed update, **no `_meta`**, text content block) still surfaces the content text and does not throw.
  - `parsePermissionRequestFrame` names the inner tool when `toolCall._meta.claudeCode.toolName` is present.
- **`mcpToolRegistry.test.tsx`** — parameterized: each built-in SDK name resolves to its `displayName`/icon and not the wrench fallback; an unmapped name still falls back.
- **`FallbackMcpToolRenderer.test.ts`** — failed card shows the decision reason when present.
- **(deferred) `extractors.test.ts`** — `extractDiffBlocks` returns blocks for `{type:'diff'}` content and null otherwise.
- **Typecheck + lint:** `pnpm --filter=@posthog/frontend typescript:check`, `pnpm --filter=@posthog/frontend format`.
- No playwright/query-count tests warranted (pure client render logic).

## Rollout / flagging

n/a — these are corrections to render logic on the existing sandbox runtime path, already gated behind `conversation.agent_runtime === 'sandbox'`. No new flag needed; the fixes only improve rendering of frames the runtime already emits. (Telemetry is unaffected: `tool_call_completed` already fires with `tool_qualified_name: resolvedKey`, which becomes the stable SDK name after sub-task A — a strict improvement, not a breaking change to event shape.)

## Effort & risk

- **Effort:** Core (A + B) is **S–M** — wire-type rewrite, a resolver param, one ingest read, a denial-reason read, ~11 registry entries, and their tests. C is a further **S** when its producer lands.
- **Risks:**
  - _Test drift (two files):_ (1) the existing `resolveToolKey` tests (`sandboxStreamLogic.test.ts:124-125`, `:294`) encode a `toolName` the real wire doesn't send for built-ins; (2) `sandboxWireTypes.test.ts:172-176`/`:297-306` encode the flat snake_case `_meta` that the type rewrite removes. Both will fail to compile/pass and must be rewritten to the empty-`toolName` + nested-`_meta` reality — this is the main correctness check; get it right or B silently does nothing.
  - _Telemetry change:_ `tool_qualified_name` for built-ins shifts from the human title to the SDK name. This is intended and better, but flag it for anyone querying that property.
  - _Speculative names:_ `MultiEdit`/`Skill` are unverified against the pinned SDK — registering them is safe (no-op if absent).
  - _Low blast radius:_ no backend, no API types, no shared components beyond reusing `MonacoDiffEditor` (deferred). Confined to the sandbox thread render chain.
