# Upstream Sync

Fork of `@anthropic-ai/claude-agent-acp`. Upstream repo: https://github.com/anthropics/claude-code

## Fork Point

- **Forked**: v0.10.9, commit `5411e0f4`, Dec 2 2025
- **Last sync**: v0.54.1, commit `8d5febf`, Jul 1 2026
- **SDK**: `@anthropic-ai/claude-agent-sdk` 0.3.197, `@agentclientprotocol/sdk` 1.1.0, `@anthropic-ai/sdk` 0.109.0

## File Mapping

| PostHog | Upstream |
|---|---|
| `conversion/tool-use-to-acp.ts` | `tools.ts` |
| `conversion/sdk-to-acp.ts` | inline in `acp-agent.ts` |
| `conversion/acp-to-sdk.ts` | inline in `acp-agent.ts` |
| `claude-agent.ts` | `acp-agent.ts` |
| `permissions/*` | inline in `acp-agent.ts` |
| `session/options.ts` | inline in `acp-agent.ts` |
| `session/commands.ts` | inline in `acp-agent.ts` |
| `hooks.ts` | `tools.ts` |
| `types.ts` | inline |

## PostHog-Only Code (Do Not Sync)

- PostHog analytics (`_posthog/*` ext notifications, `_posthog/usage_update`)
- Process lifecycle (spawn wrappers, PID tracking, `onProcessSpawned`/`onProcessExited`)
- Plan mode (`plan/`, EnterPlanMode/ExitPlanMode handlers, plan validation)
- Gateway models (`session/models.ts`, `base-acp-agent.ts`, `fetchGatewayModels`)
- AskUserQuestion handler (`questions/`, `CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL`)
- Execution modes and tool allowlists (`tools.ts`, `CodeExecutionMode`)
- MCP metadata caching (`mcp/`)
- Branch naming in system prompt
- `broadcastUserMessage` in prompt()
- `interruptReason` on cancel
- Steer mode: `_meta.steer` maps to `priority:"next"` in `promptToClaude` (`acp-to-sdk.ts`). A mid-turn branch in `prompt()` pushes the message into the running turn's input and returns immediately with a benign `end_turn` instead of queueing a new turn. Advertised via `_meta.posthog.steering:"native"` in `initialize()`
- `SYSTEM_REMINDER` stripping from Read tool results
- WebFetch `resourceLink` content enrichment
- `customTitle` in listSessions (PostHog is ahead of upstream here)
- Refusal support: `Options.fallbackModel` defaults to `FALLBACK_MODEL` in
  `session/options.ts`; `model_refusal_fallback` system messages emit a
  `_posthog/status` notification (`refusal_fallback`) in `sdk-to-acp.ts`; a
  terminal `stop_reason: "refusal"` emits `_posthog/status` (`refusal`) instead
  of upstream's raw-explanation `agent_message_chunk` (supersedes the v0.42.0
  "Refusal handling" port and the v0.44.0 `model_refusal_fallback` skip)
- SettingsManager `PreToolUse` hook for permission rules
- `ensureLocalSettings` / `clearStatsigCache`
- `ELECTRON_RUN_AS_NODE` / `ENABLE_TOOL_SEARCH` env vars

## Intentional Divergences

| Area | Upstream | PostHog | Reason |
|---|---|---|---|
| AskUserQuestion | Always disallowed | Enabled via env var + permission handler | PostHog supports structured questions |
| Model resolution | `initializationResult.models` from SDK | `fetchGatewayModels()` from gateway API | Different model backend |
| permissionMode | Hardcoded `"default"` | Reads from `meta.permissionMode` | More flexible mode selection |
| Session storage | `this.sessions[sessionId]` (multi) | `this.session` (single) | Architectural choice |
| bypassPermissions | `updatedPermissions` with `destination: "session"` | No `updatedPermissions` | Different permission persistence |
| Auth methods | `claude-ai-login` + `console-login` | Returns empty `authMethods` | Auth handled externally |
| Session fingerprinting | Implicit teardown on cwd/mcp change | Explicit `refreshSession()` | Caller-initiated is more predictable |
| Shutdown on ACP close | Process exits | No standalone process | Agent is embedded in server |
| Unsupported slash commands | Loops silently on early idle | Emits "Unsupported slash command" chunk, gated on `initializationResult().commands` so plugin/skill commands (e.g. `/skills-store`) whose echoes use a fresh uuid are not false-flagged. Lives in the consumer's idle handler: fires only when idle arrives with no active turn, an unsettled head turn whose leading command is unknown, and no pending orphan results. | The SDK consumes some slash commands without producing output (e.g. `/plugin` in non-interactive mode); without this we hang. The known-commands gate avoids racing plugin/skill loads where idle can arrive before the transformed user-message echo. |
| Prompt-loop cancel race | Per-iteration `addEventListener`/`removeEventListener` race in the consumer (#780) | `withAbort(query.next(), cancelController.signal)` helper in `utils/common.ts`, also guarding the `compact_boundary` `getContextUsage` fetch | Same effect (no listener/reaction accumulation on the long-lived wake-up promise), different helper. `withAbort` removes its abort listener as soon as `next()` settles; the consumer re-arms a fresh controller after each abort fire, matching upstream's re-arm. |
| ACP connection wiring | `agent({name}).onRequest(...).connect(stream)` builder + narrow `AcpClient` interface (#790) | Keeps `AgentSideConnection` / `ClientSideConnection` (deprecated but fully functional in ACP 1.1.0) in `acp-connection.ts` / `base-acp-agent.ts` / codex | The fork is embedded (in-process streams, `extMethod`/`extNotification` extension surface) and the deprecated classes still route optional `extMethod`/`extNotification` to the Agent/Client. Revisit when ACP removes them; permission cancellation already uses the class's generic `request(..., { cancellationSignal })`. |
| Consumer ownership | Per-session map; consumer keyed by `sessions[id]` | Single `this.session`; consumer captures `query` + `queryGeneration` and exits quietly on mismatch | `refreshSession()` (fork-only) swaps `query`/`input` in place on the same session object; the generation guard keeps a retired consumer from tearing down the refreshed session. |

## Changes Ported in v0.54.1 Sync

- **SDK bumps**: claude-agent-sdk 0.3.170 -> 0.3.197, ACP SDK 0.25.0 -> 1.1.0, anthropic SDK
  0.104.1 -> 0.109.0. The ACP 1.x major is source-compatible for the fork: the deprecated
  `AgentSideConnection`/`ClientSideConnection` classes are still shipped and still route
  `extMethod`/`extNotification` (see Intentional Divergences). Only in-repo break was the SDK
  `Query` interface gaining `setMcpPermissionModeOverride` and `reinitialize` (test mock updated).
- **Persistent consumer + turn queue** (#780, 4f273a2): The per-prompt message loop became a
  single long-lived consumer per session. `prompt()` now enqueues a `Turn` (deferred) and returns;
  the consumer drains the query stream for the session's whole life, activates turns via their
  user-message echoes (promoting the queue head for echo-less local-only/compaction results, with
  orphan-result accounting after cancels), settles turns at their terminal `result` instead of
  waiting for the SDK's trailing `idle` (which can lag behind background tasks — upstream issues
  #773/#679/#688), forwards between-turn/background output live, and rejects turns with a clear
  "session has ended" error once the stream dies (`queryClosed`). Upstream's fixes folded in:
  fresh-abort-listener per iteration (kept as `withAbort` + re-armed controller), error results
  via `failActive` without killing the consumer (replaces the drain-after-error loop, #706's
  successor), process-death teardown via `failAllTurns` + `closeQueryStream`. Fork adaptations:
  single-session, steer mode untouched (mid-turn push + benign end_turn), `interruptReason`
  carried on every cancelled settle, per-turn broadcast fired at activation (preserves the old
  "broadcast when the turn takes over" timing), the unsupported-slash-command gate re-anchored on
  "idle with an unactivated head turn", `toolUseStreamCache` cleared on cancel/error settles, and
  a `queryGeneration` guard so `refreshSession()` retires the old consumer cleanly.
- **Content-based streamed-block dedupe** (#785 12d34e6, #789 1c80bf8, #800 960f62d — ported as
  the final #800 state): `StreamedAssistantBlocks` switched from per-message-id
  `textIds`/`thinkingIds` sets to an ordered accumulated-text record; the consolidated assistant
  message prefix-diffs each block against what streamed and forwards only the un-streamed
  remainder (nothing / whole block / cut-short tail). Robust to gateways whose consolidated
  message id doesn't match the stream. Record cleared at each top-level `message_start` and after
  consumption; consumer-lived so mid-message turn activation can't drop it. New unit tests cover
  tail-forwarding, id-mismatch dedupe, residue clearing and empty-delta stalls.
- **Skip empty thinking chunks** (#793, 15fdf26): `handleThinkingChunk` drops signature-only
  (empty) thinking blocks that models with `thinking.display: "omitted"` stream; empty deltas are
  also excluded from the streamed-block record so they can't stall the diff cursor.
- **Emit tool_call before permission request** (#820, c95fc88): New agent-lived
  `emittedToolCalls` set shared between the streamed tool_use path and the permission flow.
  `requestPermissionFromClient` eagerly emits the referenced `tool_call` (Task*/TodoWrite
  excluded; Bash carries `terminal_info`) so the client has it before being asked to approve;
  whichever side runs second emits a `tool_call_update` instead of a duplicate. Pruned at
  `tool_result` alongside `toolUseCache`.
- **Permission request cancellation** (#801, 9013d1d): All five permission-request sites now go
  through `client.request(methods.client.session.requestPermission, params, { cancellationSignal:
  signal })`, so cancelling a turn sends `$/cancel_request` and the client can dismiss the open
  dialog; an abort-time rejection maps to the existing "Tool use aborted".
- **Terminal error rendering** (#776, db6eaaf): Bash `is_error` results keep flowing through the
  terminal-output `_meta` channel (when the client supports it) instead of short-circuiting to
  plain error content.
- **Bash image output** (#617, a759e64): Array tool_result content that isn't text-only (e.g. an
  image from a piped data URI) bypasses the terminal channel and surfaces as ACP content blocks
  instead of being silently dropped.
- **`informational` system subtype** (rode in with SDK 0.3.178, #777 58549ff): Surfaced as an
  `agent_message_chunk` (level folded into the text for non-info levels) so hook-blocked stops are
  no longer silent. `worker_shutting_down` no-ops via the existing `default: break`.
- **Sonnet 5 model-version matching** (#826, ef42c46): `MODEL_FAMILY_VERSION_PATTERN` accepts
  single-number generations (`5`) and `extractModelFamilyVersion` strips `[1m]`-style context
  hints before matching, so `sonnet 5` resolves and `claude-sonnet-4-6` can't cross-match a
  Sonnet 5 alias. Unit tests added.
- **Session title push at turn end** (#812, 1fe7ec0): `maybeUpdateSessionTitle` polls
  `getSessionInfo` at each `idle` and pushes a `session_info_update` (ACP 1.1) when the
  SDK-generated `customTitle`/`summary` changes.
- **Fast mode session config** (#828, fa949a2, adapted to gateway models): New `fast` on/off
  select config option, surfaced only for models in `MODELS_WITH_FAST_MODE`
  (claude-opus-4-8/-4-7). Toggling calls `query.applyFlagSettings({ fastMode })`; the intent is
  retained across model switches (`session.fastModeEnabled`), seeded from
  `initializationResult.fast_mode_state`, and reconciled with SDK-reported `fast_mode_state` on
  init and user-turn results (`cooldown` never flaps the toggle). Boolean-typed config options
  were not adopted — the renderer consumes selects; revisit if it advertises
  `sessionConfigOptions.boolean`.
- **ReportFindings tool rendering** (#826, ef42c46): Not ported to `toolInfoFromToolUse` — see
  Skipped (the fork renders unknown tools generically and PostHog has no code-review
  ReportFindings flow); re-evaluate if the SDK starts emitting it in our sessions.
- **Test mock**: added `setMcpPermissionModeOverride` and `reinitialize` to the SDK `MockQuery`
  (new methods on the SDK `Query` interface by 0.3.197).

## Skipped in v0.54.1 Sync

- **ACP builder-pattern migration** (#790, 2554c7b): Kept the deprecated connection classes —
  recorded as an Intentional Divergence (they still ship in 1.1.0 and carry the
  `extMethod`/`extNotification` surface the fork's `_posthog/*` extensions rely on).
- **Elicitation fixes** (#774 d58004a, #779 b364059): Upstream's AskUserQuestion runs through
  ACP's unstable elicitation API; ours uses its own `questions/` machinery behind the permission
  flow and the renderer does not advertise elicitation. Same standing skip as the v0.44 sync.
- **ACP logout support** (#816, 0a0468c): Fork returns empty `authMethods` (auth handled
  externally by PostHog); there is no CLI credential store to clear from the embedded agent.
- **Version flag handling** (#813, 9616bda): `src/index.ts` CLI-entrypoint concern; the fork is
  embedded in the agent server and has no standalone binary.
- **Agent selection dropdown** (#794, 5729c47): Surfaces custom main-thread agent personas
  (`supportedAgents()` minus built-ins) as an `agent` config option. PostHog drives its own
  agent concepts; defer until product wants persona selection in the picker.
- **availableModels allowlist fixes** (#768 cc2885f, #827 98c284b) and **1M inference from model
  descriptions** (#799, 508453c): All operate on upstream's SDK-settings model pipeline
  (`ANTHROPIC_CUSTOM_MODEL_OPTION`, `modelOverrides`, `ModelInfo.description` scans). The fork's
  models and context windows come from the PostHog gateway (`fetchGatewayModels`,
  `getContextWindowForModel`), which has none of those inputs.
- **ReportFindings rendering** (#826): See above — no ReportFindings flow reaches the fork today;
  the generic tool_call rendering is acceptable if it ever does.
- **`model_refusal_no_fallback` status subtype** (SDK 0.3.193, #818 5dd8746): Our
  `handleSystemMessage` status handling is non-exhaustive, so the new subtype already no-ops
  (same precedent as `thinking_tokens` / `model_refusal_fallback`).
- **Idle-time `usage_update`**: Dropped along with the #780 port (upstream removed it when turns
  began settling at their terminal result). The mid-stream and result-time usage updates remain;
  the idle-time emission double-counted cumulative loop usage in rare paths anyway.
- **Test-only upstream changes** (#769 41cde99 CLAUDE_CONFIG_DIR isolation, #792 9f38cb6 tmp
  dirs): Upstream test-harness hygiene; our tests use their own fixtures.
- **Release / CI / dep-group bumps** (#772, #775, #778, #784, #788, #795, #802, #803, #808,
  #811, #817, #821, #822, #823, #829, #831 and the pure SDK-bump commits #771, #783, #791, #798,
  #806, #807, #810, #818 beyond the versions captured above): No fork-relevant code.

## Changes Ported in v0.44.0 Sync

- **SDK bumps**: claude-agent-sdk 0.3.165 -> 0.3.170 (the 0.3.169 bump #754 was version-only),
  anthropic SDK 0.100.1 -> 0.104.1 (upstream now carries it as a dev dependency; 0.104.1 matches
  upstream HEAD), ACP SDK unchanged at 0.25.0.
- **Forward unstreamed assistant text blocks** (#757, 7ff6b7f): The consolidated assistant
  message's `text`/`thinking` blocks were always dropped as duplicates of the streamed chunks,
  which loses the whole answer behind gateways that return a turn as a single non-streamed block
  (common with OpenAI-compatible proxies). Added a per-turn `StreamedAssistantBlocks` tracker on
  `MessageHandlerContext` (populated in `handleStreamEvent` from `message_start` ids +
  `content_block_delta` types, top-level streams only); `filterAssistantContent` (replaces
  `filterMessageContent`) now drops a block only if its exact (message id, block type) pair
  streamed live or the block is empty. Subagent assistant text stays always-dropped, and the
  replay path (no tracker) keeps the legacy drop-all filter — upstream's replay never filtered, so
  this divergence is contained to `replaySessionHistory`. Covered by new unit tests in
  `conversion/sdk-to-acp.test.ts`.
- **`fallback` content block no-op** (#761, d8af943): New @anthropic-ai/sdk block type added to
  the `processContentChunk` no-op group so it doesn't trip the `unreachable` default (same
  treatment as `advisor_tool_result` / `mid_conv_system` in the v0.38 sync).
- **Test mock**: added `usage_EXPERIMENTAL_MAY_CHANGE_DO_NOT_RELY_ON_THIS_API_YET` to the SDK
  `MockQuery` (new method on the SDK `Query` interface in 0.3.170).

## Skipped in v0.44.0 Sync

- **Experimental elicitation support** (#756, 12bd276): Upstream re-enables AskUserQuestion by
  rendering it through ACP's unstable elicitation API (`unstable_createElicitation`, gated on
  `clientCapabilities.elicitation`) and forwards MCP-server elicitations the same way. Conflicts
  with our AskUserQuestion divergence (own `questions/` machinery behind
  `CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL`, plus existing AskUserQuestion rendering in
  `conversion/tool-use-to-acp.ts`), and our renderer does not advertise elicitation capabilities.
  Revisit if the renderer adopts ACP elicitation; the `elicitation_complete` system subtype also
  stays unhandled (we never create elicitations, and `handleSystemMessage` defaults to no-op).
- **`model_refusal_fallback` system subtype** (#761, d8af943): Upstream adds it to their
  exhaustive status-TODO case group. Our `handleSystemMessage` ends in `default: break`, so the
  new subtype already no-ops harmlessly (same precedent as the v0.38 `thinking_tokens` skip).
- **Release / dep-group / dev-dep bumps** (#752, #758, #759, #763): No fork-relevant code beyond
  the SDK versions captured above. (#751 `validateCwd` appears in upstream's v0.43.0 changelog but
  predates our v0.42.0 sync point and is already in the fork at `claude-agent.ts`.)

## Changes Ported in v0.42.0 Sync

- **SDK bumps**: claude-agent-sdk 0.3.156 -> 0.3.165, ACP SDK 0.22.1 -> 0.25.0, anthropic SDK
  unchanged at 0.100.1.
- **ACP SDK 0.25.0 model-state removal** (#737, 32175b8): 0.24.0 deleted `SessionModelState`,
  `SetSessionModelRequest/Response`, `ModelInfo`, and the `models` field on every session lifecycle
  response; model selection moved entirely into `SessionConfigOption` (category "model"). Our fork
  already drove model selection through config options, so this just removed the vestigial legacy
  path: dropped those imports, the `unstable_setSessionModel` method, and the `models` build/return
  in `createSession` / `getExistingSessionState` / `loadSession`. The codex adapter's
  `response.models?.currentModelId` read was replaced with a `modelIdFromConfigOptions()` helper
  (codex `models.ts`). Verified the renderer reads only `configOptions`, never `.models`.
- **ACP SDK 0.25.0 `deleteSession` rename** (#753, 0dbccf5): No-op for us — our fork never
  implemented `unstable_deleteSession`, and the method is optional on the `Agent` interface.
- **Refusal handling** (SDK 0.3.162, #740, add7e31): Capture the refused assistant message's
  `stop_details.explanation`; the terminal `result` (stop_reason "refusal") emits it as an
  `agent_message_chunk` and returns ACP's dedicated `refusal` stop reason instead of letting the
  `is_error` path surface it as an internal error.
- **commands_changed** (SDK 0.3.162, #740, add7e31): New `system` subtype handled inline in the
  prompt loop — pushes `available_commands_update` straight from `message.commands` (rather than
  re-querying `supportedCommands()`, which only ever reflects the init list) and refreshes
  `session.knownSlashCommands` so the unsupported-slash-command gate stays accurate.
- **Optimized marker stripping** (#738, 895422c): `stripMarkerTags` rewritten as a single-pass
  scanner in `conversion/sdk-to-acp.ts`, removing the `[\s\S]*?` backtracking risk on pathological
  input.
- **Force-cancel backstop** (#742, cffea4b): Added per-turn `cancelController` + `forceCancelTimer`
  on `Session` and a mutable `forceCancelGraceMs` (30s) on the agent. The prompt loop races
  `query.next()` against the cancel signal; `interrupt()` arms a grace-period timer that aborts it,
  so a wedged SDK that never yields after interrupt (issue #680, e.g. a blocking `TaskOutput` poll)
  returns "cancelled" instead of hanging. Adapted to our single-session model; preserves the
  `interruptReason` meta on the forced return.
- **Cross-family model match fix** (#731, f4704c1): `scoreModelMatch` (session/models.ts) now
  returns 0 when only the context-hint token matched, so `claude-opus-4-6[1m]` can't resolve to
  `sonnet[1m]` purely on the shared "1m" token. Layers on top of our existing
  `modelVersionsCompatible` filter.
- **compact_boundary getContextUsage** (#747, 398f763): compact_boundary now fetches the
  authoritative post-compaction `used` via `query.getContextUsage()` (helper
  `fetchContextUsedTokens`), falling back to 0 on failure. `size` still comes from the
  gateway-learned window (getContextUsage under-reports 1M windows). Our fork-specific
  `promptReplayed = true` side effect is preserved.
- **New SDK message handling** (#747, 398f763): `tool_progress` -> `tool_call_update` `in_progress`
  with `elapsedTimeSeconds`; `rate_limit_event` -> `usage_update` carrying `_claude/rateLimit`;
  `permission_denied` -> `tool_call_update` `failed` (in `handleSystemMessage`); `mirror_error` ->
  logged (history-persistence failure / potential data loss on resume).
- **Prune tool cache** (#748, ec14211): `toolUseCache` was never cleared in our fork (set once in
  the constructor, accumulated for the whole agent lifetime). Now pruned at `tool_result` time. The
  PostToolUse hook closes over the tool name + bash command instead of re-reading the cache, so the
  Edit/Write diff survives any hook/result reordering. We did NOT adopt upstream's per-session cache
  move (we are single-session) or its `backgroundTerminals` deletion.
- **Test mock**: added `reloadSkills` to the SDK `MockQuery` (new method on the SDK `Query`
  interface in 0.3.165).

## Skipped in v0.42.0 Sync

- **Message ids** (#750, 18516a3): Upstream records an ACP `messageId` -> SDK uuid map for a future
  fork/rewind feature, explicitly "NOT READ YET". We don't consume it, it adds a `Session` field and
  threads `messageId` through many `toAcpNotifications` call sites, so it is deferred until we wire
  up rewind. (ACP 0.25.0 does expose the `messageId` field, so the port is unblocked when wanted.)
- **resolveThinkingConfig** (#747, 398f763): Upstream maps the legacy `MAX_THINKING_TOKENS` env var
  to the SDK's new `thinking` option. Our fork never reads `MAX_THINKING_TOKENS` (model setup is
  gateway-driven via `session/options.ts`), so there is nothing to migrate.
- **Pure dep-group / release / CI bumps** (#736, #741, #745, #728, #743): No fork-relevant code
  beyond the SDK versions captured above.

## Changes Ported in v0.30.0 Sync

- **SDK bumps**: claude-agent-sdk 0.2.112 -> 0.2.114, ACP SDK 0.16.1 -> 0.19.0, anthropic SDK -> 0.89.0
- **Null-safe usage tokens** (v0.29.2): Guard against null usage fields from SDK
- **SettingsManager race fix** (v0.25.0): `initPromise` prevents concurrent `initialize()`/`setCwd()` corruption
- **Malformed settings warning** (v0.25.0): Log warning for non-ENOENT settings file errors
- **Idle state end-of-turn** (v0.23.0): `CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS=1` + `session_state_changed` idle handler
- **Mid-stream usage updates** (v0.29.1): Fire `usage_update` from `message_start`/`message_delta` stream events
- **Raw SDK message relay** (v0.27.0): `emitRawSDKMessages` on `NewSessionMeta` for opt-in diagnostics
- **Effort level sync** (v0.25.x): `xhigh` level added, `applyFlagSettings` on effort change
- **Auto permission mode** (v0.25.0): Added to `CODE_EXECUTION_MODES`, available modes, ExitPlanMode options

## Changes Ported in v0.39.0 Sync

- **SDK bumps**: claude-agent-sdk 0.3.154 -> 0.3.156, anthropic SDK 0.100.0 -> 0.100.1 (ACP SDK
  unchanged at 0.22.1). v0.3.155 was not published to npm; the fix lives in 0.3.156.
- **Opus 4.8 thinking-blocks fix** (upstream v2.1.156): The SDK was modifying thinking blocks in a
  way that produced the legacy `thinking: { type: "enabled", budget_tokens: N }` request shape,
  which `claude-opus-4-8` rejects with HTTP 400 (`thinking.type.enabled is not supported for this
  model. Use thinking.type.adaptive and output_config.effort`). 0.3.156 now emits
  `thinking: { type: "adaptive" }` + `output_config: { effort }` for Opus 4.8 while keeping the
  legacy shape for Opus 4.7 / Sonnet 4.6 where the API still accepts it. No in-repo code change
  needed; `options.effort` in `session/options.ts` and `query.applyFlagSettings({ effortLevel })`
  in `claude-agent.ts` keep their current call sites.

## Changes Ported in v0.38.0 Sync

- **SDK bumps**: claude-agent-sdk 0.3.144 -> 0.3.154, anthropic SDK 0.96.0 -> 0.100.0 (ACP SDK
  unchanged at 0.22.1).
- **Compaction state-flag fix** (#716, a172885): SDK 0.3.154 emits the terminal `status` carrying
  `compact_result` twice for failed compactions. Added a per-turn `compactionInProgress` flag in
  `prompt()` so the user sees a single `Compacting completed.` / `Compacting failed: <reason>`
  chunk. Manual `/compact` outcomes now surface here rather than via `compact_boundary` (which only
  fires when there's content to compact).
- **System-role guard on user/assistant handler** (#716, a172885): Added an early return in
  `handleUserAssistantMessage` for `message.message.role === "system"`, covering both upstream's
  `<local-command-stdout>` strip branch guard and the broader assistant-handler guard. Avoids
  rendering SDK-injected system reminders as user-visible chunks.
- **New no-op content block types** (#716, a172885): Added `advisor_tool_result` and
  `mid_conv_system` cases to `processContentChunk` so unknown content blocks don't trip the
  `unreachable` default.
- **Opus 4.8 model entries** (#718, 98b54a0): Added `claude-opus-4-8` to gateway model maps with
  1M context, effort and xhigh-effort support. MCP injection auto-included (Haiku exclusion only).

## Skipped in v0.38.0 Sync

- **Remove hide Claude auth flag** (#707, 7ed1daf): Our fork already returns `authMethods: []`
  unconditionally; no flag to remove.
- **`thinking_tokens` status case** (#716, a172885): Our `handleSystemMessage` switch on
  `status === "compacting"` is non-exhaustive (no default `unreachable`), so unknown status values
  already no-op harmlessly.
- **Empty CI-retry commit** (#718, 98b54a0): No code change in the commit itself; the model entries
  it carried are ported above.
- **`MessageDisplay` hook + `SessionStart` reloadSkills/sessionTitle** (SDK 0.3.152): Available in
  the bumped SDK but not wired into our fork; upstream doesn't consume them in #716 either. Defer
  to a focused PR if we want the capability.

## Changes Ported in v0.37.0 Sync

- **SDK bumps**: claude-agent-sdk 0.2.114 -> 0.3.144, ACP SDK 0.19.0 -> 0.22.1, anthropic SDK 0.89.0 -> 0.96.0
- **TodoWrite -> Task tools migration** (SDK 0.3.142): Replaced TodoWrite snapshot tool with incremental
  TaskCreate/TaskUpdate/TaskGet/TaskList. Added `conversion/task-state.ts` and `createTaskHook` to mirror the
  SDK `TaskCreated`/`TaskCompleted` hook events into a per-session task map; plan entries are derived from
  Map insertion order (preserves upstream ordering semantics).
- **MCP_CONNECTION_NONBLOCKING=0** (SDK 0.3.142): SDK changed MCP servers to background-connect by default;
  set env to restore blocking-connect behavior so MCP tools are available on first prompt.
- **ACP SDK 0.22 breaking changes**: Renamed `unstable_resumeSession` -> `resumeSession`; new
  `McpSdkServerConfig` variant (`type: "sdk"`) in the `McpServerConfig` union. Our
  `parseMcpServers` only accepts `http`/`sse`/stdio entries, so `sdk` falls through and is
  implicitly dropped (no explicit filter needed).
- **Skills option** (SDK 0.2.133): `'Skill'` in `allowedTools` deprecated; replaced with `skills` option.
- **Memory recall tool calls** (#703, a0bfb98): Emit a `tool_call` for SDK `memory_recall` events so the
  UI shows what memories were surfaced; addresses phantom MEMORY.md read attempts.
- **Write diff fix** (#618, 8d7e220): `toolUpdateFromEditToolResponse` now also processes `Write` tool
  responses so overwrites show real diffs instead of optimistic "creation" diffs.
- **Local-command-stdout render** (#649, 3b9b7d5): Strip marker tags from `<local-command-stdout>` content
  and render remaining prose so custom slash commands and skill expansions reach the UI.
- **Cancelled vs end_turn** (#694, 2414a6f): `session_state_changed: idle` handler now reports
  `stopReason: "cancelled"` when the session was interrupted.
- **Recover prompt stream** (#706, 2711f50): After a failed turn, drain the trailing
  `session_state_changed: idle` so the next prompt's first `query.next()` doesn't short-circuit.
- **additionalDirectories field** (#684, f37e9a0): Accept the official ACP field on session lifecycle
  requests; advertise via `sessionCapabilities.additionalDirectories`. Legacy `_meta.additionalRoots` still
  honored as fallback.
- **availableModels allowlist** (#637, 867a3a0): `ClaudeCodeSettings.availableModels` array merged-and-deduped
  across settings sources, then applied to gateway model options via `applyAvailableModelsAllowlist`.
- **Model alias version match** (#702, e1e1c69): Refuse cross-version alias matches in `resolveModelPreference`
  so `claude-opus-4-6` doesn't get copied onto the `opus` alias when it resolves to 4.7.
- **Hide /clear** (#705, cfce130): `/clear` removed from advertised commands; clients should use
  `session/new` for the same effect.
- **No-op ping events** (#698, 694221a): `streamEventToAcpNotifications` no-ops `ping` keep-alive events
  instead of falling through to `unreachable` and spamming stderr.

## Skipped in v0.37.0 Sync

- **Avoid redundant initial model sync** (#704, b275f6f): Our flow already guards `setModel` behind
  `!isResume && resolvedSdkModel !== DEFAULT_MODEL`, so the upstream optimization is redundant.
- **Default effort option** (#701, 9e259d1): Our effort options are model-class-based rather than
  SDK-supplied; the implicit no-override path already covers the "let SDK decide" case.
- **Gate auto mode on model support** (#604, ec47d34): Our `auto` mode is gated behind `ALLOW_BYPASS`,
  not per-model `supportsAutoMode`. Per-model gating would be a larger refactor.

## Skipped in v0.30.0 Sync

- **Separate auth methods** (v0.25.0): PostHog returns empty authMethods
- **Session fingerprinting** (v0.25.3): PostHog uses explicit `refreshSession()` instead
- **Process exit on ACP close** (v0.27.0): PostHog embeds agent in server

## Next Sync

1. Check upstream changelog since v0.54.1
2. Diff upstream source against PostHog using the file mapping above
3. Port in phases: bug fixes first, then features
4. After each phase: `pnpm --filter agent typecheck && pnpm --filter agent build && pnpm lint`
5. After all phases: `pnpm typecheck && pnpm test`
6. Update this file
