# 04 — Prompts migration

This spec covers the **Prompts** slice of the migration described in [`00_OVERVIEW.md`](./00_OVERVIEW.md). Read that document first — it establishes the adapter-mediated architecture (`Conversation.agent_runtime === 'sandbox'` routes through the Django adapter at `ee/hogai/sandbox/` to a cloud-agent Task/Run), the "no repository / no PR" posture, and the phasing order. This spec assumes you've also skimmed [`01_CONTEXT.md`](./01_CONTEXT.md), which locks the contract that **dynamic per-turn context is prepended to the user message as a `<posthog_context>` block (by the adapter), not the system prompt** — this document owns everything *else* in the prompt.

Scope of this document: how every prompt segment in `posthog/ee/hogai/chat_agent/prompts/` (and the mode-specific siblings) maps onto the sandbox's `systemPrompt` slot, where the dynamic `{{{var}}}` variables get resolved server-side at Run-create, what happens to "modes" when the agent runtime no longer has a graph-level mode concept, which MCP servers replace the LangGraph `toolkit.py`, and how `APPENDED_INSTRUCTIONS` collides with PostHog AI. Out of scope: the dynamic context payload (`01_CONTEXT.md`), tool-call rendering (`03_RICH_UI.md`), the Task/Run wire (`02_CORE.md`).

---

## 1. Today: how Max's prompt is built

### 1.1 Segment catalog

Today the agent prompt is composed by `ChatAgentPromptBuilder` ([`ee/hogai/chat_agent/prompt_builder.py:107-127`](../../posthog/ee/hogai/chat_agent/prompt_builder.py)) into one `system` LangChain message, with a second `system` message carrying core memory.
Every named segment lives in `posthog/ee/hogai/chat_agent/prompts/`.
The table below catalogs each segment, where it's defined, what it contains, and rough size.

| Segment | File:line | What it contains | Size (chars) |
|---|---|---|---|
| `ROLE_PROMPT` | [`base.py:1-3`](../../posthog/ee/hogai/chat_agent/prompts/base.py) | One-sentence identity ("You are PostHog AI…"). | ~150 |
| `TONE_AND_STYLE_PROMPT` | [`base.py:5-17`](../../posthog/ee/hogai/chat_agent/prompts/base.py) | PostHog voice guidelines; mentions whimsical loading copy. | ~750 |
| `WRITING_STYLE_PROMPT` | [`base.py:19-31`](../../posthog/ee/hogai/chat_agent/prompts/base.py) | American English, Oxford comma, sentence case, en-dash > em-dash, no "click here" links. | ~700 |
| `PROACTIVENESS_PROMPT` | [`base.py:33-40`](../../posthog/ee/hogai/chat_agent/prompts/base.py) | "Be proactive only in response to user asks." | ~350 |
| `BASIC_FUNCTIONALITY_PROMPT` | [`base.py:42-76`](../../posthog/ee/hogai/chat_agent/prompts/base.py) | Enumerates collected data types (events, persons, sessions, properties, recordings) and created data types (actions, insights, warehouse, SQL, surveys, dashboards, cohorts, flags, notebooks, errors, interview topics, activity logs). Embeds `{{{groups_prompt}}}`. SQL-variables guidance. | ~2.4 KB |
| `SLASH_COMMANDS_PROMPT` | [`base.py:78-89`](../../posthog/ee/hogai/chat_agent/prompts/base.py) | Lists `/init`, `/remember`, `/usage`, `/feedback`, `/ticket`. | ~650 |
| `SWITCHING_MODES_PROMPT` | [`base.py:91-144`](../../posthog/ee/hogai/chat_agent/prompts/base.py) | When/when-not/how to use `switch_mode`. Includes three reasoning examples. | ~2.5 KB |
| `TASK_MANAGEMENT_PROMPT` | [`base.py:146-190`](../../posthog/ee/hogai/chat_agent/prompts/base.py) | `todo_write` policy + two narrative examples. | ~1.9 KB |
| `DOING_TASKS_PROMPT` | [`base.py:192-200`](../../posthog/ee/hogai/chat_agent/prompts/base.py) | "User is a product engineer", recommends `todo_write` + search/read, flags `<system_reminder>` semantics. | ~700 |
| `PRODUCT_ADVOCACY_PROMPT` | [`base.py:202-234`](../../posthog/ee/hogai/chat_agent/prompts/base.py) | "Recommend PostHog over Sentry/Datadog/Amplitude/Mixpanel/etc." Product list. | ~2.4 KB |
| `TOOL_USAGE_POLICY_PROMPT` | [`base.py:238-245`](../../posthog/ee/hogai/chat_agent/prompts/base.py) | Tool parallelism rules; `web_search` standalone; retry policy; pre-check docs before claiming PostHog can't do something. | ~700 |
| `AGENT_PROMPT` | [`base.py:247-275`](../../posthog/ee/hogai/chat_agent/prompts/base.py) | The Mustache wrapper that interpolates the segments above + `{{{billing_context}}}`, `{{{groups_prompt}}}`, `{{{switching_to_plan}}}`. | template |
| `AGENT_CORE_MEMORY_PROMPT` | [`base.py:277-280`](../../posthog/ee/hogai/chat_agent/prompts/base.py) | Wraps `{{{core_memory}}}` + a one-liner on memory semantics. | template |
| `CONTEXTUAL_TOOLS_REMINDER_PROMPT` | [`base.py:282-288`](../../posthog/ee/hogai/chat_agent/prompts/base.py) | `<system_reminder>` block injected per-turn listing currently-available contextual tools. | template |
| `CHAT_PLAN_AGENT_PROMPT` | [`plan.py:1-33`](../../posthog/ee/hogai/chat_agent/prompts/plan.py) | Mustache wrapper used only in plan mode. Re-uses many of the base segments, swaps in plan-mode pieces. | template |
| `CHAT_PLAN_MODE_PROMPT` | [`plan.py:35-51`](../../posthog/ee/hogai/chat_agent/prompts/plan.py) | "You are in planning mode. Three tasks: clarify → `finalize_plan` → switch to execution." | ~700 |
| `CHAT_ONBOARDING_TASK_PROMPT` | [`plan.py:53-80`](../../posthog/ee/hogai/chat_agent/prompts/plan.py) | "Evaluate clarity, ask at most 3 questions via `create_form`, skip if already clear." | ~1.1 KB |
| `SWITCHING_TO_EXECUTION_PROMPT` | [`plan.py:82-86`](../../posthog/ee/hogai/chat_agent/prompts/plan.py) | "Once plan is approved, `switch_mode` to execution." | ~150 |
| `SWITCHING_TO_PLAN_PROMPT` | [`plan.py:88-145`](../../posthog/ee/hogai/chat_agent/prompts/plan.py) | When to *enter* plan mode from execution; behind `posthog-plan-mode` flag. | ~1.8 KB |
| `PLANNING_TASK_PROMPT` | [`core/plan_mode/prompts.py:5-35`](../../posthog/ee/hogai/core/plan_mode/prompts.py) | The plan-notebook template (sections: Understanding / Approach / Metrics / Outcome). | ~700 |
| `EXECUTION_CAPABILITIES_PROMPT` | [`core/plan_mode/prompts.py:38-49`](../../posthog/ee/hogai/core/plan_mode/prompts.py) | "After planning, you'll have these tools + modes:" enumerates `{{{default_tools}}}` and `{{{available_modes}}}`. | template |
| `ROOT_GROUPS_PROMPT` | [`core/agent_modes/prompt_builder.py:17-21`](../../posthog/ee/hogai/core/agent_modes/prompt_builder.py) | "The user has defined the following groups: {{{groups}}}." | ~80 |
| `ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT` | [`core/agent_modes/prompt_builder.py:23-30`](../../posthog/ee/hogai/core/agent_modes/prompt_builder.py) | "If user asks about billing, use `read_data` kind=billing_info." | ~500 |
| `ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT` | [`core/agent_modes/prompt_builder.py:32-37`](../../posthog/ee/hogai/core/agent_modes/prompt_builder.py) | "User isn't admin; tell them to contact an admin." | ~250 |
| `ROOT_BILLING_CONTEXT_ERROR_PROMPT` | [`core/agent_modes/prompt_builder.py:39-43`](../../posthog/ee/hogai/core/agent_modes/prompt_builder.py) | "Direct user to PostHog support." | ~150 |
| `SWITCH_MODE_PROMPT` | [`tools/switch_mode.py:19-44`](../../posthog/ee/hogai/tools/switch_mode.py) | Tool description for `switch_mode` — embedded into the tool schema, not the system prompt body. Lists `{{{default_tools}}}` and `{{{available_modes}}}`. | template |
| `HOGQL_GENERATOR_SYSTEM_PROMPT` | [`chat_agent/sql/prompts.py:1-176`](../../posthog/ee/hogai/chat_agent/sql/prompts.py) | Standalone system prompt for the HogQL generator sub-agent. Massive — function casing rules, person_id join limitation, visualization guidance, expressions docs, supported functions, supported aggregations, project schema interpolation. | ~36 KB after `{{{sql_expressions_docs}}}`, `{{{sql_supported_functions_docs}}}`, `{{{sql_supported_aggregations_docs}}}`, `{{{schema_description}}}` interpolation. |
| Product-analytics mode-specific todo examples | [`core/agent_modes/presets/product_analytics.py:24-44`](../../posthog/ee/hogai/core/agent_modes/presets/product_analytics.py) | Dashboard-creation `todo_write` example + reasoning. | ~1 KB |
| SQL mode-specific todo examples | [`core/agent_modes/presets/sql.py:20-76`](../../posthog/ee/hogai/core/agent_modes/presets/sql.py) | Three concrete `todo_write` examples for SQL tasks. | ~2.5 KB |

**Total** before mode-specific pieces is around 13 KB of static prose; with the SQL prompt expanded, peak prompt size approaches **~50 KB**.

### 1.2 Variable resolution — where each `{{{var}}}` comes from

The system prompt and the secondary "core memory" prompt are both Mustache-templated. `format_prompt_string` ([`utils/prompt.py:6-33`](../../posthog/ee/hogai/utils/prompt.py)) wraps `PromptTemplate.from_template(..., template_format="mustache")` so unspecified variables raise rather than silently emit empty strings. The variables in play:

| Variable | Where resolved today | Frequency | Owned by |
|---|---|---|---|
| `{{{role}}}` | Hard-coded constant `ROLE_PROMPT` — `format_prompt_string(AGENT_PROMPT, role=ROLE_PROMPT, …)` ([`prompt_builder.py:113-127`](../../posthog/ee/hogai/chat_agent/prompt_builder.py)). | Static. | `prompt_builder.py` |
| `{{{tone_and_style}}}`, `{{{writing_style}}}`, `{{{proactiveness}}}`, `{{{basic_functionality}}}`, `{{{slash_commands}}}`, `{{{switching_modes}}}`, `{{{task_management}}}`, `{{{doing_tasks}}}`, `{{{product_advocacy}}}`, `{{{tool_usage_policy}}}` | Same — hard-coded constants. | Static. | `prompt_builder.py` |
| `{{{switching_to_plan}}}` | `SWITCHING_TO_PLAN_PROMPT` if `has_plan_mode_feature_flag(team, user)`, else empty string ([`prompt_builder.py:108-112`](../../posthog/ee/hogai/chat_agent/prompt_builder.py)). | Per-team. | `prompt_builder.py` |
| `{{{billing_context}}}` | `BillingPromptMixin._get_billing_prompt()` ([`core/agent_modes/prompt_builder.py:61-80`](../../posthog/ee/hogai/core/agent_modes/prompt_builder.py)) — checks `_context_manager.get_billing_context()` and `check_user_has_billing_access()`. Returns one of `ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT`, `ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT`, `ROOT_BILLING_CONTEXT_ERROR_PROMPT`. | Per-user, per-organization. Can change on day-to-day basis (subscription / role flips). | `BillingPromptMixin` |
| `{{{groups_prompt}}}` | `_context_manager.get_group_names()` (returns the team's `GroupTypeMapping` rows) → formatted with `ROOT_GROUPS_PROMPT` if non-empty ([`core/agent_modes/prompt_builder.py:103`](../../posthog/ee/hogai/core/agent_modes/prompt_builder.py)). | Per-team. Stable for hours/days. | `AgentPromptBuilderBase.get_prompts()` |
| `{{{core_memory}}}` | `AssistantContextMixin._aget_core_memory_text()` ([`core/mixins.py:34-40`](../../posthog/ee/hogai/core/mixins.py)) — pulls the team's `CoreMemory.formatted_text`. Empty string if disabled by `is_core_memory_disabled(team, user)`. Lives in `posthog_corememory`. | Per-team. Mutated by `/init` and `/remember` slash commands. | `AssistantContextMixin` |
| `{{{plan_mode}}}` | Hard-coded `CHAT_PLAN_MODE_PROMPT` constant. | Static, but only present when in plan mode. | `ChatAgentPlanPromptBuilder` |
| `{{{onboarding_task}}}`, `{{{planning_task}}}`, `{{{switch_to_execution}}}` | Hard-coded constants. | Static. | `ChatAgentPlanPromptBuilder` |
| `{{{execution_capabilities}}}` | Itself a Mustache template — gets formatted with `{{{default_tools}}}` and `{{{available_modes}}}`. | Dynamic — depends on team's feature flags (e.g. `phai_tasks`, `task_tool`, `memory_tool`, `mcp_servers`). | `ChatAgentPlanPromptBuilder` |
| `{{{default_tools}}}` | `_get_default_tools_prompt(team, user, state, config, default_tool_classes=DEFAULT_TOOLS)` ([`tools/switch_mode.py:90-110`](../../posthog/ee/hogai/tools/switch_mode.py)) — resolves each tool class to an instance and joins their names. | Dynamic — feature-flag gated. | `_get_default_tools_prompt` |
| `{{{available_modes}}}` | `_get_modes_prompt(team, user, state, config, context_manager, mode_registry)` ([`tools/switch_mode.py:56-87`](../../posthog/ee/hogai/tools/switch_mode.py)) — enumerates `mode_registry` (from `ee/hogai/chat_agent/mode_manager.py`), instantiates each preset's toolkit, returns one bullet per mode with its tool list. | Dynamic — depends on mode registry, which is feature-flag gated. | `_get_modes_prompt` |
| `{{{tools}}}` (in `CONTEXTUAL_TOOLS_REMINDER_PROMPT`) | `_context_manager.get_contextual_tools()` rendered via `format()` ([`context/context.py:472`](../../posthog/ee/hogai/context/context.py)). | Per-turn. | `AssistantContextManager._get_contextual_tools_reminder()` |
| `{{{sql_expressions_docs}}}`, `{{{sql_supported_functions_docs}}}`, `{{{sql_supported_aggregations_docs}}}` | Hard-coded literals in [`chat_agent/sql/prompts.py:178-952`](../../posthog/ee/hogai/chat_agent/sql/prompts.py). | Static. | `chat_agent/sql/nodes.py` |
| `{{{schema_description}}}` | Live introspection of the team's ClickHouse + warehouse schema by the SQL generator node. | Per-team. | `chat_agent/sql/nodes.py` |

The thing to internalize: in today's stack every variable resolves *just-in-time* inside a LangGraph node, immediately before the model call. The new world has no such hook — `clientConnection.newSession({ _meta: { systemPrompt } })` ([`agent-server.ts:709`](../../Twig/packages/agent/src/server/agent-server.ts), `CLOUD_AGENTS_FRONTEND_SPEC.md` § 10.5) takes a single fully-formed string. Resolution must move to **Run-create time** in PostHog cloud.

### 1.3 Mode-specific prompt assembly

PostHog AI today uses a graph-level "mode" concept (`AgentMode` enum — `posthog/schema.py`) implemented by `mode_manager` ([`ee/hogai/chat_agent/mode_manager.py`](../../posthog/ee/hogai/chat_agent/mode_manager.py)) and the preset registry ([`ee/hogai/core/agent_modes/presets/`](../../posthog/ee/hogai/core/agent_modes/presets/)). The relevant modes:

| Mode (`AgentMode.*`) | Preset file | Tools | Prompt augmentation |
|---|---|---|---|
| `PRODUCT_ANALYTICS` | [`presets/product_analytics.py`](../../posthog/ee/hogai/core/agent_modes/presets/product_analytics.py) | `CreateInsightTool`, `UpsertDashboardTool`, `UpsertAlertTool` | Adds `DASHBOARD_CREATION_TODO_EXAMPLE_EXAMPLE` to `POSITIVE_TODO_EXAMPLES`. |
| `SQL` | [`presets/sql.py`](../../posthog/ee/hogai/core/agent_modes/presets/sql.py) | `ExecuteSQLTool` (which embeds the entire `HOGQL_GENERATOR_SYSTEM_PROMPT` as a sub-agent) | Adds three SQL-specific `todo_write` examples. |
| `ERROR_TRACKING` | [`presets/error_tracking.py`](../../posthog/ee/hogai/core/agent_modes/presets/error_tracking.py) | error-tracking-specific upsert tools | — |
| `SESSION_REPLAY` | [`presets/session_replay.py`](../../posthog/ee/hogai/core/agent_modes/presets/session_replay.py) | session-replay tools | — |
| `LLM_ANALYTICS` | [`presets/llm_analytics.py`](../../posthog/ee/hogai/core/agent_modes/presets/llm_analytics.py) | llm-analytics tools | — |
| `SURVEY` | [`presets/survey.py`](../../posthog/ee/hogai/core/agent_modes/presets/survey.py) | survey upsert tools | — |
| `FLAGS` | [`presets/flags.py`](../../posthog/ee/hogai/core/agent_modes/presets/flags.py) | feature-flag tools | — |
| `PLAN` (synthetic) | `ChatAgentPlanPromptBuilder` | `ReadTaxonomyTool`, `SearchTool`, `TodoWriteTool`, `SwitchModeTool`, `CreateFormTool`, `FinalizePlanTool` (+ `ManageMemoriesTool` if flag) | Substitutes whole `CHAT_PLAN_AGENT_PROMPT` template. |
| `EXECUTION` (synthetic) | `ChatAgentPromptBuilder` | All `DEFAULT_TOOLS` + per-preset extensions | Uses `AGENT_PROMPT` template. |

The mode is stored in `AssistantState.mode`. `SwitchModeTool` ([`tools/switch_mode.py:112-180`](../../posthog/ee/hogai/tools/switch_mode.py)) is what the model invokes to flip it. The next loop tick reloads the toolkit and the prompt template, then resumes with conversation history preserved.

### 1.4 LangGraph plumbing

For completeness, the sequence inside `posthog/ee/hogai/chat_agent/` per turn:

1. Conversation API ([`ee/api/conversation.py`](../../posthog/ee/api/conversation.py)) handles `POST /conversations/stream/`, serializes input into `HumanMessage(ui_context=…)`.
2. The graph (built in [`graph.py`](../../posthog/ee/hogai/chat_agent/graph.py)) dispatches to the current mode's executable. `ChatAgentExecutable` calls `ChatAgentPromptBuilder.get_prompts(state, config)`.
3. `get_prompts()` runs `_get_billing_prompt()`, `_aget_core_memory_text()`, `get_group_names()` in parallel via `asyncio.gather`, formats `AGENT_PROMPT` + `AGENT_CORE_MEMORY_PROMPT`, returns `ChatPromptTemplate.from_messages(...).format_messages(...)`.
4. The toolkit ([`toolkit.py`](../../posthog/ee/hogai/chat_agent/toolkit.py)) is resolved separately — feature-flag-gated, asynchronously. `ChatAgentToolkitManager` decorates with contextual tools, MCP installations, and (conditionally) AWS-Bedrock-incompatible `web_search`.
5. The two LangChain messages plus the tool definitions go into the model adapter (Anthropic / Bedrock / Bedrock-gateway).

Nothing about this is portable to the sandbox as-is — we throw away the graph and rebuild "give me the composed string and the toolkit" as two Run-create-time helpers.

---

## 2. Tomorrow: how the sandbox consumes a prompt

### 2.1 `systemPrompt` via `newSession._meta`

The sandbox boots, the agent-server initializes the ACP `clientConnection`, then calls ([`agent-server.ts:856-952`](../../Twig/packages/agent/src/server/agent-server.ts), `CLOUD_AGENTS_FRONTEND_SPEC.md` § 10.5):

```
clientConnection.newSession({
  cwd,
  mcpServers,
  _meta: {
    sessionId,
    taskRunId,
    systemPrompt,          // <-- this is what we own
    model?,
    allowedDomains,
    jsonSchema,
    permissionMode,
    claudeCode,
  },
})
```

`systemPrompt` is either a plain string (the agent prepends nothing — the model sees it verbatim) or a `{ append: string }` object (Claude prepends its built-in `claude_code` preset). The shape is defined in [`packages/agent/src/server/schemas.ts:32-46`](../../Twig/packages/agent/src/server/schemas.ts):

```ts
const claudeCodeConfigSchema = z.object({
  systemPrompt: z
    .union([
      z.string(),
      z.object({
        type: z.literal("preset"),
        preset: z.literal("claude_code"),
        append: z.string().optional(),
      }),
    ])
    .optional(),
  // ...
})
```

For PostHog AI we want **the string form, with no `claude_code` preset**. The Claude Code preset assumes a coding-agent posture (Read/Edit/Bash, git etiquette, repository navigation) that's wrong for PostHog AI's analytics posture. Sending a string disables the preset entirely (`buildSystemPrompt` in [`adapters/claude/session/options.ts:60-90`](../../Twig/packages/agent/src/adapters/claude/session/options.ts) returns `customPrompt + APPENDED_INSTRUCTIONS` for string inputs).

### 2.2 `APPENDED_INSTRUCTIONS` and how they collide with PostHog AI

[`adapters/claude/session/instructions.ts`](../../Twig/packages/agent/src/adapters/claude/session/instructions.ts) defines an unconditional `APPENDED_INSTRUCTIONS` constant that's concatenated to any system prompt (`buildSystemPrompt` glues it on — both for string-form and object-form input). Three sub-blocks:

1. **`BRANCH_NAMING`** — tells the agent to create a branch prefixed `posthog-code/` whenever in detached HEAD. **Wrong for PostHog AI** — there's no repository, no detached HEAD, no need to think about branches at all.
2. **`PLAN_MODE`** — instructs the agent on Claude Code's built-in `EnterPlanMode` tool. **Partially overlaps** with PostHog AI's own plan-mode concept (see § 4). Could be acceptable if we map "plan mode" onto the ACP `permission_mode: "plan"` channel (option C below).
3. **`MCP_TOOLS`** — "If MCP returns a denial, relay it. If MCP errors, troubleshoot — don't blame settings." **Always correct.** Keep.

Combined with `buildSessionSystemPrompt` ([`agent-server.ts:1529-1726`](../../Twig/packages/agent/src/server/agent-server.ts)), which appends a `cloudAppend` block per the table below, the unmodified pipeline would dilute PostHog AI's system prompt with several KB of repository/PR copy.

`buildCloudSystemPrompt` branches:

| Condition | Adds |
|---|---|
| `prUrl` set, `shouldAutoCreatePr === true` | "Push to existing PR" + attribution instructions. |
| `prUrl` set, `shouldAutoCreatePr === false` | "Stop with local changes ready for review." |
| `!repositoryPath` (No Repository Mode), `createPr === false` | "You may clone and edit but don't create branches/PRs." + the "You ARE the analytics platform — use MCP tools" copy. |
| `!repositoryPath`, `createPr` truthy | "Clone repo if user asks, draft PR if user asks." |
| `repositoryPath` set, `shouldAutoCreatePr === false` | "Don't open a PR unless asked." |
| `repositoryPath` set, `shouldAutoCreatePr === true` | The full "Create `posthog-code/*` branch + draft PR" copy. |

For PostHog AI we want the **No Repository Mode, `createPr === false`** branch — it's already most of what we want, but its `publishInstructions` still mention cloning, and its leading paragraph mentions code tasks. We accept those (they're guarded by "if user asks") rather than fork the whole function.

**Recommendation (§ 2.3 below) parameterizes which extras get appended.** Until that lands, the No Repository Mode branch is the right interim posture: it explicitly says "do NOT create branches, commits, push changes, or open pull requests in this run", which short-circuits 90% of the misfit.

### 2.3 No-repository / no-git posture

When the adapter creates a Task for a sandbox-runtime conversation, it sets:

```
{
  // Conversation row carries agent_runtime === 'sandbox' + task_run_id FK back to the Run created below.
  // Task itself:
  repository: null,           // null repo
  github_integration: null,   // null GH integration
  config: {
    createPr: false,          // see also: state.create_pr in the Run record
  },
  // ...
}
```

When the agent-server is launched (CLI: `agent-server --task-id=… --run-id=… --no-repository`), `this.config.repositoryPath` is unset and `this.config.createPr` is `false`. This drives `buildCloudSystemPrompt` into the No Repository Mode + `createPr === false` branch.

The result is the *cloud-append* string (still passed in via `buildSessionSystemPrompt` as `{ append: cloudAppend }`):

```
# Cloud Task Execution — No Repository Mode

You are a helpful assistant with access to PostHog via MCP tools. You can help with both code tasks and data/analytics questions.

When the user asks about analytics, ...
- Use your PostHog MCP tools to query data, search insights, and provide real answers
- Do NOT tell the user to check an external analytics platform — you ARE the analytics platform
- ...

When the user asks for code changes or software engineering tasks:
- Let them know you can help but don't have a repository connected for this session
- ...

When the user asks for code changes:
- You may clone a repository and make local edits in that clone
- Do NOT create branches, commits, push changes, or open pull requests in this run

Important:
- Prefer using MCP tools to answer questions with real data over giving generic advice.
## Attribution
Do NOT use Claude Code's default attribution ...
```

The PostHog AI prompt we generate becomes the **string before** that block. Net result the model sees:

```
<PostHog AI prompt (~13 KB)>

<cloudAppend (~1 KB) — the No Repository Mode block above>

<APPENDED_INSTRUCTIONS — BRANCH_NAMING + PLAN_MODE + MCP_TOOLS>
```

The first ~1 KB of duplication ("you ARE the analytics platform — use MCP tools" — overlaps with `BASIC_FUNCTIONALITY_PROMPT` + `TOOL_USAGE_POLICY_PROMPT`) is acceptable noise. The `BRANCH_NAMING` block (~250 chars) is dead weight but harmless — there's no repository to branch in.

**Decision: don't fork the agent-server.** Accept the redundancy and the dead-weight branch-naming block. The cost (a few hundred extra tokens per Run, paid once thanks to prompt-caching) is far smaller than the cost of forking a hot-path file and keeping it in sync across two repos.

**Follow-up (post-MVP):** add a `--no-cloud-prompt-extras` flag (or `--cloud-prompt-mode=posthog_ai`) to the agent-server that short-circuits `buildCloudSystemPrompt` entirely when set, returning only the attribution + MCP-tools blocks. Tracked in the open-questions list (§ 8).

---

## 3. Segment-by-segment migration table

Format: one row per source segment. Action is one of:

- **Keep** — copy verbatim into the new build function. No edits.
- **Edit** — light rewrite (rephrase a sentence, remove a now-irrelevant claim). Body documented in the row.
- **Drop** — segment not needed; behavior moves elsewhere or is obsolete.
- **Move-to-tool** — segment was conveying behavior that the LLM should pick up from a tool description; move the content there.

The "target" column names the slot in the new prompt (see § 6.2 for ordering) or the target tool description.

| Segment | Action | Target | Rationale |
|---|---|---|---|
| `ROLE_PROMPT` | Keep | New prompt § 1 (Role). | Identity is identity; "PostHog AI, PostHog's AI agent". |
| `TONE_AND_STYLE_PROMPT` | Keep | New prompt § 2 (Voice). | Keep "Pondering…/Hobsnobbing…" line — frontend still shows those loading copies (`02_CORE.md` ports `thinkingMessages.ts`). |
| `WRITING_STYLE_PROMPT` | Keep | New prompt § 3 (Writing style). | Style guide is stable. |
| `PROACTIVENESS_PROMPT` | Keep | New prompt § 4 (Proactiveness). | Behavior guidance, transport-agnostic. |
| `BASIC_FUNCTIONALITY_PROMPT` | Edit | New prompt § 5 (Capabilities and data model). | Remove the line "Do not generate any code like Python scripts. Users don't have the ability to run code." — in the sandbox the agent *can* run code locally via the Bash tool (if surfaced via `posthog-code` MCP). Replace with "You may compute small things inline; do not produce code for the user unless asked." Otherwise verbatim. `{{{groups_prompt}}}` interpolated server-side (§ 6.3). |
| `SLASH_COMMANDS_PROMPT` | Edit | New prompt § 6 (Slash commands). | Drop `/usage` if `02_CORE.md` § 8 routes it differently (cloud-agent usage is computed from `_posthog/usage_update` notifications, not a slash command). Otherwise verbatim. Confirm with `02_CORE.md` owner. |
| `SWITCHING_MODES_PROMPT` | Drop | — | The "modes" concept changes shape in the sandbox (see § 4). The replacement is either zero text (option A), per-Task profile (option B), or a short note about `permission_mode` (option C). The 2.5 KB of "when/how to switch modes" copy goes away regardless. |
| `TASK_MANAGEMENT_PROMPT` | Move-to-tool | `todo_write` MCP tool description. | The two narrative examples belong on the tool's `description` field — that's where Claude Code reads them from. The system prompt then just has one line "Use `todo_write` to plan multi-step work; mark items done as you finish." |
| `DOING_TASKS_PROMPT` | Edit | New prompt § 7 (Doing tasks). | Drop the `<system_reminder>` paragraph — that's a LangChain idiom we don't need in MCP-tool-result land. Keep the "use search and read extensively" guidance. |
| `PRODUCT_ADVOCACY_PROMPT` | Keep | New prompt § 8 (Product advocacy). | Verbatim. Keep the explicit competitor list. |
| `TOOL_USAGE_POLICY_PROMPT` | Edit | New prompt § 9 (Tool usage policy). | Drop the `web_search` standalone clause — in the sandbox model, `web_search` is just another tool (Claude SDK exposes it as `WebSearch`); the "standalone" treatment was an artifact of the LangGraph executor. Keep the docs-pre-check line. |
| `AGENT_PROMPT` (the wrapper) | Drop | — | Replaced by `build_posthog_ai_system_prompt` (§ 6). The Mustache wrapper is now a Python f-string concatenation in the build function. |
| `AGENT_CORE_MEMORY_PROMPT` | **Drop** | — | Core memory is dropped entirely from the sandbox runtime (per `00_OVERVIEW.md` § 3). No core-memory block in the unified prompt; no `{{core_memory}}` resolution. See `TODO.md` for the backfill conversation. |
| `CONTEXTUAL_TOOLS_REMINDER_PROMPT` | Drop | — | Replaced by `01_CONTEXT.md`'s active-context manifest + the MCP server tool surface. The model learns "what tools are available" by reading the tool list, not a system-reminder block; the model learns "what's pinned" from the per-turn `<attached_context>` block. |
| `CHAT_PLAN_AGENT_PROMPT` (wrapper) | Drop | — | Plan mode reconciliation (§ 4) decides whether this content survives and in what form. With the recommended option C, only `CHAT_PLAN_MODE_PROMPT`, `CHAT_ONBOARDING_TASK_PROMPT`, `PLANNING_TASK_PROMPT` survive — and they're gated behind `permission_mode === "plan"`. |
| `CHAT_PLAN_MODE_PROMPT` | Keep (gated) | New prompt § 10 (Plan-mode addendum), only emitted when `permission_mode === "plan"`. | Conditional segment. The "three tasks" enumeration (clarify → plan → switch to execution) still applies. |
| `CHAT_ONBOARDING_TASK_PROMPT` | Keep (gated) | New prompt § 10. | Same gating. |
| `SWITCHING_TO_EXECUTION_PROMPT` | Edit (gated) | New prompt § 10. | Rephrase from "use `switch_mode` to flip to execution" to "call `posthog_plan_finalize_plan` to lock the plan; the user will be prompted to approve". The actual transition is `ExitPlanMode` (Claude Code's built-in) when option C is chosen — see § 4. |
| `SWITCHING_TO_PLAN_PROMPT` | Edit (gated) | New prompt § 9b (Plan-mode hint). | Convert "Use `switch_mode` to enter plan mode" to "Use `EnterPlanMode` (built-in) when the task warrants planning — see below for criteria". Conditional on `posthog-plan-mode` flag. |
| `PLANNING_TASK_PROMPT` | Keep (gated) | New prompt § 10. | Plan-notebook template stays. |
| `EXECUTION_CAPABILITIES_PROMPT` | Drop | — | Listing every default tool and every available mode in the system prompt is no longer needed — Claude SDK exposes the tool list directly to the model. Drop the `{{{default_tools}}}` and `{{{available_modes}}}` placeholders entirely. (Confirm by snapshot-testing that the model still finds the right tools without the enumeration — it should, given MCP discovery happens automatically.) |
| `ROOT_GROUPS_PROMPT` | Keep | Interpolated into `BASIC_FUNCTIONALITY_PROMPT` via the `{{groups_prompt}}` slot in § 6.3. | Same content. |
| `ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT` | Keep | New prompt § 11 (Billing). One of three variants. | Selection logic identical to `BillingPromptMixin._get_billing_prompt`. |
| `ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT` | Keep | New prompt § 11. | — |
| `ROOT_BILLING_CONTEXT_ERROR_PROMPT` | Keep | New prompt § 11. | — |
| `SWITCH_MODE_PROMPT` | Drop or move | Tool description for the legacy `switch_mode` tool. | If option A or option C is chosen (§ 4), the `switch_mode` tool goes away entirely → drop. If option B is chosen, the tool description moves to the MCP server that surfaces it. |
| `HOGQL_GENERATOR_SYSTEM_PROMPT` | Move-to-tool | `posthog-data` MCP server: `execute_sql` tool description, plus a "system instructions" preface returned with every tool call. | This 36 KB prompt was the SQL sub-agent's *own* system prompt — it never sat in the main chat agent's prompt. In the new world, the SQL sub-agent is the `execute_sql` MCP tool. Two delivery shapes available: (a) embed the function-casing rules and join-limitation guidance in the tool's `description` field (sub-1-KB summary) and stash the full docs in an MCP resource (`schema://hogql/functions`, `schema://hogql/aggregations`, `schema://hogql/expressions`) that the model fetches on first SQL question; (b) pass the whole thing as a "system reminder" `_meta` block on each `execute_sql` tool result. Recommendation: (a) — better caching, agent can read once and reuse via Claude's context window. |
| `POSITIVE_TODO_EXAMPLES` (per-mode) | Move-to-tool | `todo_write` MCP tool description. | The dashboard-creation example, the SQL examples — they're examples of how to use `todo_write` for a given domain. They belong on the tool's description, picked dynamically based on installed MCP servers (see § 5.3). |
| `SQL_EXPRESSIONS_DOCS`, `SQL_SUPPORTED_FUNCTIONS_DOCS`, `SQL_SUPPORTED_AGGREGATIONS_DOCS` | Move-to-tool | MCP resources under `posthog-data`. | The model fetches via the standard MCP resource flow. Don't inline. |
| `schema_description` (SQL sub-agent's schema-introspection variable) | Move-to-tool | `posthog-data`'s `read_data_warehouse_schema` MCP tool. | Already a separate tool today ([`tools/read_data_warehouse_schema/`](../../posthog/ee/hogai/tools/read_data_warehouse_schema/)) — just exposed via MCP. |

---

## 4. Mode-switching: keep, drop, or transform

This is the highest-leverage decision in the spec. PostHog AI's `SwitchModeTool` is a hot-loop mechanism — the model calls it, the LangGraph executor flips `state.mode`, the next iteration uses a different toolkit and prompt template. The sandbox has no equivalent hook: a Run is single-session, tool list is fixed at `newSession()` time (modulo `_posthog/refresh_session`).

### 4.1 Option A — unified prompt

**Idea:** Drop modes entirely. One long systemPrompt that describes the agent's full capability set. The toolkit at Run start contains every tool from every mode.

**Pros:**

- Simplest mental model. One Run, one prompt, all tools.
- No transitions to engineer; no transition latency.
- The model picks tools based on the user's question alone, without a mode-routing step.

**Cons:**

- Prompt bloat. Concatenating the static prose for product-analytics, SQL, error-tracking, session-replay, LLM-analytics, surveys, and flags — even just the 1-paragraph descriptions of each — adds ~5 KB. Each preset's `POSITIVE_TODO_EXAMPLES` adds another 3-4 KB. The SQL prompt alone (if moved into the main prompt) adds 36 KB.
- Tool-selection confusion. With ~25 tools available simultaneously, Claude routinely picks suboptimal tools (model-quality observation from production usage of similar wide toolkits — confirm with AI team's eval data).
- Auth scope creep. Some modes today expose write tools (`UpsertDashboardTool`, `UpsertAlertTool`, `UpsertExperimentTool`) that we currently gate behind `acceptEdits` permission mode. Always-on means always-asked, increasing dangerous-operation prompts (`03_RICH_UI.md` § 5).

**When this works:** if the AI team's evals show Claude-with-bigger-toolkit performs as well as Claude-with-mode-routing, this is the simplest path.

### 4.2 Option B — multiple sandbox profiles

**Idea:** User picks a mode at Task creation. The Task records `mode: "sql"` (etc.). Sandbox launches with that mode's `systemPrompt` and `mcpServers`. Mode cannot change mid-Task.

**Pros:**

- Smaller per-Task prompt: only the relevant mode's prose.
- Smaller toolkit: only the relevant mode's tools, lower miss-tool rate.
- Cheaper: smaller prompt = cheaper prompt cache.

**Cons:**

- Loses today's most-loved property: fluid mode switching. User types "find users who spent $50, then build a funnel for them" — today that's a `sql → product_analytics` flip, in option B that's "sorry, please start a new chat in product-analytics mode and reference the user list".
- Forces a mode picker at Task creation, in a chat surface that today has none.
- Cross-mode work requires multiple Tasks, which makes history confusing.

**When this works:** if PostHog AI's user behavior is dominated by single-mode chats (data point we don't yet have — `posthog-ai-mode-distribution` query in PostHog itself can answer it).

### 4.3 Option C — permission_mode reuse + content sections

**Idea:** Map the user-facing "plan vs execute" axis to ACP `permission_mode: "plan" | "default" | "acceptEdits" | "bypassPermissions"` (`CLOUD_AGENTS_FRONTEND_SPEC.md` § 10.5). The other axes (`sql / product_analytics / error_tracking / …`) **collapse into tool-availability gates plus prompt sections in one unified prompt**, but with two key affordances:

1. The unified prompt has a section "Capabilities by domain" with a one-line summary of each mode and a pointer to the corresponding MCP server / tools. The model reads this and routes to tools accordingly.
2. The sandbox starts with **all** MCP servers connected, but feature-flag-gated. If a server isn't applicable (e.g. the user doesn't have LLM analytics enabled), it's not in the `--mcpServers` list.
3. Plan mode uses Claude Code's built-in `EnterPlanMode` tool (already in the `claude_code` preset). When `permission_mode` flips to `plan`, the agent-server's `_posthog/mode_change` notification fires; the frontend shows the plan-mode banner.
4. The user can switch the permission mode mid-Run via `set_config_option("mode", "plan" | "default" | …)` ([`CLOUD_AGENTS_FRONTEND_SPEC.md` § 6.6](../CLOUD_AGENTS_FRONTEND_SPEC.md)). The agent picks up the change without a session restart.

**Pros:**

- Reuses an existing mechanism (`permission_mode`) instead of inventing one.
- Single Run per chat; conversation history never fragments.
- The "plan" UX (today's biggest mode-switching use case) is preserved with first-class agent-server support.
- Other "modes" (product analytics, SQL, error tracking) become MCP tool groupings, which is what they actually are in implementation today.

**Cons:**

- Sub-mode-specific prompt augmentations (e.g. SQL's "person_id join limitation" guidance) must live on the tool descriptions or MCP resources, not in the system prompt. This is a stricter architectural constraint than today.
- The "I'm now in SQL mode" affordance is gone. We replace it with whatever UI the frontend renders when the agent calls into the `execute_sql` tool (`03_RICH_UI.md` § 4 owns the rendering).
- Today's `switch_mode` tool disappears. Any in-flight conversations that reference "switch_mode" need a soft migration during the rollout (see § 7).

### 4.4 Recommendation

**Adopt option C.**

Rationale:

- It mirrors what PostHog Code does today on the same sandbox — proven shape.
- It's the only option where today's most-loved property (fluid mid-conversation routing) survives unchanged.
- The `permission_mode === "plan"` mapping captures the highest-value piece of today's mode system (plan/execute) and inherits the agent-server's built-in plan-mode plumbing (`EnterPlanMode`, `_posthog/mode_change` notification, mid-Run `set_config_option`).
- Sub-domain "modes" become tool groupings, which is the simpler and more honest model — there was never a model-level difference between "SQL mode" and "product-analytics mode" except for which tools were available.

The mode-specific prose that has real evergreen value (SQL function casing rules, person_id join limitation, dashboard-creation todo example) moves to MCP tool descriptions and MCP resources where it belongs (and where it benefits from per-tool prompt caching).

The one piece we lose: the LangGraph executor's ability to *not* show the user "switching to SQL mode…" status updates while it's reasoning about which mode to switch to. We compensate by surfacing the `_posthog/progress` notifications driven by the agent's own narration ("I'll write a SQL query…"). This is what PostHog Code does today; it works.

### 4.5 Mode-specific prompt migration plan (with option C)

For each preset, decide where its prose lives:

| Preset | Body today | Migration target |
|---|---|---|
| `product_analytics` | `ProductAnalyticsAgentToolkit.POSITIVE_TODO_EXAMPLES` + `PRODUCT_ANALYTICS_MODE_DESCRIPTION` | The dashboard-creation example → `todo_write` MCP tool description (selected when the team has product analytics enabled). The mode description → tool description for `create_insight` and `upsert_dashboard` MCP tools. |
| `sql` | `SQLAgentToolkit.POSITIVE_TODO_EXAMPLES` (3 examples) + `SQL_MODE_DESCRIPTION` + the full `HOGQL_GENERATOR_SYSTEM_PROMPT` (36 KB) | Examples → `todo_write` tool description (SQL-team-flagged). Function-casing rules → `execute_sql` MCP tool description (always sent). Person_id join limitation → ditto. Expressions/functions/aggregations docs → MCP resources (`schema://hogql/...`) fetched lazily. Mode description → `execute_sql` tool description. |
| `error_tracking` | Toolkit + `ERROR_TRACKING_MODE_DESCRIPTION` | Tool descriptions for `posthog_data_get_error_tracking_issue` etc. |
| `session_replay` | Toolkit + `SESSION_REPLAY_MODE_DESCRIPTION` | Tool descriptions for `posthog_data_query_session_recordings_list` etc. |
| `llm_analytics` | Toolkit + `LLM_ANALYTICS_MODE_DESCRIPTION` | Tool descriptions for `posthog_data_query_llm_*` etc. |
| `survey` | Toolkit + `SURVEY_MODE_DESCRIPTION` | Tool descriptions for survey-related tools. |
| `flags` | Toolkit + `FLAGS_MODE_DESCRIPTION` | Tool descriptions for `feature-flag-*` tools. |

The shared "Capabilities by domain" section in the unified system prompt (§ 6.2 § C) gets *one line per domain*, pointing at the corresponding MCP server. The detailed prose lives on the tool — read once by the model, cached.

---

## 5. The MCP tool surface

### 5.1 Tool → MCP server mapping

Every tool in [`ee/hogai/chat_agent/toolkit.py`](../../posthog/ee/hogai/chat_agent/toolkit.py) and the per-preset toolkits maps to an MCP server. Several tools cluster together by what they touch; group them into a small number of servers.

| Tool today | Defined in | Target MCP server | Tool name on the server | Notes |
|---|---|---|---|---|
| `ReadTaxonomyTool` | [`tools/read_taxonomy/`](../../posthog/ee/hogai/tools/read_taxonomy/) | **`posthog-data`** | `posthog_data_read_taxonomy` | Same args, returns event/property/group/cohort taxonomy. |
| `ReadDataTool` | [`tools/read_data/`](../../posthog/ee/hogai/tools/read_data/) | `posthog-data` | `posthog_data_read_data` | All today's `kind=…` variants (insights, billing_info, person, group, etc.). |
| `SearchTool` | [`tools/search.py`](../../posthog/ee/hogai/tools/search.py) | `posthog-data` | `posthog_data_search` | Both docs and full-text search across PostHog entities. |
| `ListDataTool` | [`tools/list_data.py`](../../posthog/ee/hogai/tools/list_data.py) | `posthog-data` | `posthog_data_list_data` | List dashboards / insights / cohorts / flags / experiments / surveys. |
| `ExecuteSQLTool` | [`tools/execute_sql/`](../../posthog/ee/hogai/tools/execute_sql/) | `posthog-data` | `posthog_data_execute_sql` | The SQL sub-agent. Tool description embeds the function-casing rules + person_id join warning. MCP resources `schema://hogql/{functions,aggregations,expressions}` carry the long-form docs. |
| `CreateInsightTool` | [`tools/create_insight.py`](../../posthog/ee/hogai/tools/create_insight.py) | `posthog-data` | `posthog_data_create_insight` | Write tool — surfaces a permission_request via `permission_mode: "acceptEdits"`. |
| `UpsertDashboardTool` | [`tools/upsert_dashboard/`](../../posthog/ee/hogai/tools/upsert_dashboard/) | `posthog-data` | `posthog_data_upsert_dashboard` | Write tool. |
| `UpsertAlertTool` (alerts product) | `products/alerts/backend/max_tools.py` | `posthog-data` | `posthog_data_upsert_alert` | Write tool. |
| `CreateNotebookTool` | [`tools/create_notebook/`](../../posthog/ee/hogai/tools/create_notebook/) | **`posthog-notebook`** | `posthog_notebook_create` | Write tool. |
| `TodoWriteTool` | [`tools/todo_write.py`](../../posthog/ee/hogai/tools/todo_write.py) | Claude Code built-in **OR** **`posthog-tasks`** | `TodoWrite` (built-in) or `posthog_tasks_todo_write` | Decision in § 5.2 below. Claude Code already ships a `TodoWrite` tool; if its semantics match (they do — same status enum, same description shape), use it and skip building our own. Otherwise build `posthog-tasks`. |
| `ManageMemoriesTool` | [`tools/manage_memories.py`](../../posthog/ee/hogai/tools/manage_memories.py) | **DROP** | — | Core memory is dropped entirely for the sandbox runtime (per `00_OVERVIEW.md` § 3). `/remember` becomes a no-op for the new runtime — see `02_CORE.md` § 7 and `TODO.md` for the backfill question. |
| `CallMCPServerTool` | [`tools/call_mcp_server/`](../../posthog/ee/hogai/tools/call_mcp_server/) | n/a — **user-installed MCPs pass through directly** | — | Today this tool was a meta-tool that proxied calls to the user's MCP installations. In the sandbox model, those installations are just MCP servers in `--mcpServers` — no proxy needed. |
| `TaskTool` (PostHog Code integration) | [`tools/task.py`](../../posthog/ee/hogai/tools/task.py) | **`posthog-code`** | `posthog_code_create_task`, `posthog_code_get_task`, etc. | Routes PostHog AI → PostHog Code. The team-flag `task_tool` already gates today; carry forward. |
| `CreateTaskTool`, `RunTaskTool`, `GetTaskRunTool`, `GetTaskRunLogsTool`, `ListTasksTool`, `ListTaskRunsTool`, `ListRepositoriesTool` | `products/tasks/backend/max_tools.py` | `posthog-code` (same server as `TaskTool`) | `posthog_code_*` | All seven — grouped under `posthog-code`. Behind the `has_phai_tasks` flag today. |
| `CreateFormTool` | [`tools/create_form.py`](../../posthog/ee/hogai/tools/create_form.py) | **Client-side tool — see `03_RICH_UI.md` § 4** | (renders UI; not a backend MCP) | We mention it here only as boundary. The form-submit answers come back as user-message follow-ups. Owned by `03_RICH_UI.md`. |
| `FinalizePlanTool` | [`tools/finalize_plan/`](../../posthog/ee/hogai/tools/finalize_plan/) | Built-in: `ExitPlanMode` (Claude Code) | — | With option C (§ 4), Claude Code's built-in `ExitPlanMode` does the job. Drop our custom tool. The plan body it would have written goes via a notebook the agent creates (per `PLANNING_TASK_PROMPT`'s template). |
| `SwitchModeTool` | [`tools/switch_mode.py`](../../posthog/ee/hogai/tools/switch_mode.py) | n/a (drop) | — | With option C (§ 4), drop entirely. The mode concept is gone; the permission-mode toggle is via `set_config_option`. |
| Contextual tools (`useMaxTool`-registered) | various (e.g. `UpsertFlagFilterTool` lives next to the scene logic) | Frontend dispatched, see `03_RICH_UI.md` § 4 | — | Owned by `03_RICH_UI.md`. They're not backend MCP tools; they're browser-rendered actions the model calls. |
So we end up with **four new MCP servers** (down from six in the prior iteration):

1. `posthog-data` — taxonomy, search, list, read_data, execute_sql, create_insight, upsert_dashboard, upsert_alert (plus per-domain reads: error tracking, session replay, surveys, flags, llm analytics, and the new `read_dashboard` / `read_insight` / `read_event_definition` / `read_action` / `read_evaluation` entity reads referenced from `<posthog_context>` wrappers per `01_CONTEXT.md`).
2. `posthog-notebook` — `posthog_notebook_create`, `posthog_notebook_update`, `posthog_notebook_get`, `posthog_notebook_list`.
3. `posthog-tasks` — only if Claude Code's built-in `TodoWrite` doesn't fit; otherwise skip.
4. `posthog-code` — gated by `has_phai_tasks` flag; surfaces the PostHog Code integration.

`posthog-memory` (was: dedicated memory MCP) and `posthog-context` (was: on-demand entity-detail MCP) are **gone** — core memory is dropped (per `00_OVERVIEW.md`) and entity-detail fetch happens via the existing `posthog-data` reads triggered by the `<posthog_context>` wrapper (per `01_CONTEXT.md`).

Plus zero-to-many **user-installed MCP servers** — those go straight into `--mcpServers` without a proxy.

### 5.2 Where each MCP server runs

Three deployment choices for each MCP server:

| Choice | Description | Pros | Cons |
|---|---|---|---|
| **In-sandbox** | Compiled into the agent-server image; mounted via stdio. | No network hop; auth-free (already inside the trust boundary). | Each tool change requires an image rebuild + cold-start cost; can't update server-side code without rolling the sandbox. |
| **Sidecar** | Runs in the same pod as the sandbox; reachable via localhost HTTP. | Cheap to iterate; same trust boundary. | Adds infra surface; another process to crash. |
| **Remote HTTP MCP** | Hosted by PostHog cloud (Django + `services/mcp/`); reachable via `--mcpServers` URL with JWT auth. | Updates ship without sandbox roll; central rate limiting; same code path as user-installed MCPs. | Network hop on every call (typically <50ms within same region); JWT auth surface. |

**Recommendation per server:**

| Server | Where | Rationale |
|---|---|---|
| `posthog-data` | **Remote HTTP MCP at `https://{region}.posthog.com/mcp/posthog-data/`** | Wraps existing DRF viewsets — code already lives in Django. Centralized rate limiting matters here (these tools issue ClickHouse queries). The MCP framework under `services/mcp/` already serves this pattern. |
| `posthog-notebook` | **Remote HTTP MCP** | Same reasoning. Notebook CRUD is in Django. |
| `posthog-tasks` | Skip (use Claude Code's built-in `TodoWrite`) — confirmed in § 5.1. | The built-in matches our semantics. |
| `posthog-code` | **Remote HTTP MCP** at the PostHog Code service. | Routes through the existing PostHog Code backend. |
| User-installed MCPs | Whatever URL the user supplied. | Pass through directly. |

The JWT-auth pattern for remote HTTP MCPs is documented in `CLOUD_AGENTS_FRONTEND_SPEC.md` § 10.4. Every request includes `Authorization: Bearer <sandbox-jwt>`, the Django middleware extracts `team_id` + `user_id`, and tool implementations scope all queries by team.

### 5.3 Tool description authoring (the LLM reads these — they matter)

In the sandbox model, the **tool description is the only way to teach the model how to use the tool** — there's no equivalent of LangGraph's pre-prompt injection. The tool description string is what the model reads when deciding whether to call a tool.

Today, tool descriptions are short. Going forward they need to absorb a lot of prose that previously lived in the system prompt:

- **`posthog_data_execute_sql`** — description includes: function-casing rules (camelCase, not snake_case); the person_id join limitation block; key visualization guidance; SQL-variables convention; "queries must filter `events` by `timestamp`". Target length: 1.5-2 KB.
- **`posthog_data_search`** — description includes: `kind=docs` should be used before claiming a feature doesn't exist; `kind=events`, `kind=actions`, etc. distinctions. Target length: 500-800 chars.
- **`posthog_data_read_data`** — description includes: every `kind=…` variant with one example use. Target length: 1-1.5 KB.
- **`posthog_notebook_create`** — description includes: the notebook template (from `PLANNING_TASK_PROMPT`). Target length: 500 chars.
- **`posthog_memory_manage`** — description includes: when to save (proactively, after `/remember`, when user asserts a fact about their business). Target length: 300-500 chars.
- **`posthog_code_create_task`** — description includes: when to offer a code task vs an inline answer. Target length: 500 chars.
- **`TodoWrite`** (built-in Claude Code) — we can't author its description, but we can include the example workflows in the system prompt instead. Two example narratives (~1 KB each).

The combined target is "system prompt drops by ~5 KB, tool descriptions absorb ~5 KB". Net: per-call prompt size is roughly unchanged, but the costs amortize better because tool descriptions cache at a different cache key (Claude's tool-result prompt-cache boundary is per-tool).

Authoring style guidelines for tool descriptions:

- Start with a one-sentence summary (what + when).
- Then list arguments — what each does, with examples.
- Then list pitfalls — the things the model might do wrong.
- End with one or two concrete invocation examples.
- Avoid mode-specific qualifiers; assume the agent is general-purpose.

These descriptions are how we replace the lost `SWITCHING_MODES_PROMPT` content. The model picks tools by reading them; clearer descriptions mean fewer wrong calls.

### 5.4 Hot-loading via `_posthog/refresh_session`

When the user installs a new MCP server mid-conversation, the browser/cloud calls ([`CLOUD_AGENTS_FRONTEND_SPEC.md` § 6.7](../CLOUD_AGENTS_FRONTEND_SPEC.md)):

```
POST /command/
{
  jsonrpc: "2.0",
  id: "<cmd-id>",
  method: "_posthog/refresh_session",
  params: {
    mcpServers: [
      { type: "http", name: "github-issues", url: "https://...", headers: [...] },
      // ...the existing posthog-data, posthog-notebook entries...
    ],
  },
}
```

The agent-server reinitializes the ACP session with the new MCP-server list, keeping conversation history. No new Run. No new `systemPrompt`. The model sees the new tools on the next turn.

Dynamic tool injection is gone (per `00_OVERVIEW.md` § 3 and `01_CONTEXT.md` § 2) — scenes can no longer register tools the agent invokes. `_posthog/refresh_session` is reserved for user actions that genuinely add or remove an MCP server at the project level (e.g., installing a new user MCP), not for scene navigation.

**The systemPrompt does NOT change across `refresh_session`.** This is structural — the systemPrompt was baked at `newSession()` time. The model learns about the new tools purely from the tool list. This means: every per-team consideration that goes in the system prompt must be Run-stable. Anything that may change mid-Run must go through `set_config_option` + tool-list refresh, not the system prompt.

Concrete consequence for this spec: **feature flags evaluated for the system prompt must be evaluated once at Run-create time and frozen for the Run's lifetime.** If the team toggles `has_plan_mode_feature_flag` mid-Run, the current Run still uses the previous prompt. New Runs use the new prompt. This matches how Claude Code already behaves with `--claudeCodeConfig`.

---

## 6. The new build function: `build_posthog_ai_system_prompt`

### 6.1 Signature and inputs

Location: `posthog/ee/hogai/chat_agent/sandbox_prompt.py` (new module).

```python
async def build_posthog_ai_system_prompt(
    team: Team,
    user: User,
    *,
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"] = "default",
    context_summary: dict | None = None,  # NOT the full per-turn context — that goes elsewhere
    feature_flag_snapshot: FeatureFlagSnapshot | None = None,
) -> str:
    """Compose the systemPrompt for a PostHog AI sandbox Run.

    Called once at Run creation. The returned string goes into
    `clientConnection.newSession({ _meta: { systemPrompt } })`.
    """
```

Inputs:

- **`team`** — for `groups_prompt` (group type names), `billing_context` (subscription state).
- **`user`** — for `billing_context` (admin role), feature-flag evaluation.
- **`permission_mode`** — drives whether the plan-mode section is included. Run-create takes `state.initial_permission_mode` if specified, else the default (`"default"` for Claude, `"auto"` for Codex — `CLOUD_AGENTS_FRONTEND_SPEC.md` § 10.5).
- **`context_summary`** — *optional* small static slice of context that's truly per-Run-immutable (e.g. project name, default timezone). Anything that may change scene-by-scene goes via `01_CONTEXT.md`'s per-turn channel, not here.
- **`feature_flag_snapshot`** — a frozen view of every flag that affects prompt composition. If omitted, the function reads flags itself (one round-trip). Threading the snapshot lets the Task-create endpoint share one flag-evaluation across many derived values.

Output: a single fully-formatted string, ready to pass through to `systemPrompt`.

No side effects. Pure function over its inputs.

### 6.2 Composition order

The composed prompt structure, in order:

```
<identity>
{role}                                          # ROLE_PROMPT verbatim
</identity>

{tone_and_style}                                # TONE_AND_STYLE_PROMPT verbatim

{writing_style}                                 # WRITING_STYLE_PROMPT verbatim

{proactiveness}                                 # PROACTIVENESS_PROMPT verbatim

<capabilities>
{basic_functionality}                           # BASIC_FUNCTIONALITY_PROMPT edited (§ 3) + interpolated {{groups_prompt}}
</capabilities>

<capabilities_by_domain>
- Product analytics: use `posthog_data_create_insight`, `posthog_data_upsert_dashboard`, ...
- SQL / data warehouse: use `posthog_data_execute_sql`. The function name casing is camelCase.
- Error tracking: use `posthog_data_*_error_tracking_*` tools.
- Session replay: use `posthog_data_*_session_recording_*` tools.
- LLM analytics: use `posthog_data_*_llm_*` tools.
- Surveys: use `posthog_data_*_survey_*` tools.
- Feature flags: use `posthog_data_*_feature_flag_*` tools.
- Notebooks: use `posthog_notebook_*` tools.
- User-installed MCPs and the user's PostHog Code service may add more.
</capabilities_by_domain>

{slash_commands}                                # SLASH_COMMANDS_PROMPT edited (§ 3)

{doing_tasks}                                   # DOING_TASKS_PROMPT edited (§ 3)

{product_advocacy}                              # PRODUCT_ADVOCACY_PROMPT verbatim

{tool_usage_policy}                             # TOOL_USAGE_POLICY_PROMPT edited (§ 3)

# Plan-mode addendum, emitted only when permission_mode == "plan":
<plan_mode>
{chat_plan_mode}                                # CHAT_PLAN_MODE_PROMPT
{chat_onboarding_task}                          # CHAT_ONBOARDING_TASK_PROMPT
{planning_task}                                 # PLANNING_TASK_PROMPT
{switching_to_execution}                        # SWITCHING_TO_EXECUTION_PROMPT — rewritten per § 3
</plan_mode>

# Switching-to-plan hint, emitted only when has_plan_mode_feature_flag is true AND permission_mode != "plan":
<plan_mode_hint>
{switching_to_plan_rewritten}                   # SWITCHING_TO_PLAN_PROMPT rewritten to talk about EnterPlanMode
</plan_mode_hint>

<billing_context>
{billing_context}                               # one of three variants — see § 6.3
</billing_context>

<project_context>
Project name: {project_name}.                   # from context_summary
Default timezone: {project_timezone}.
Region: {region}.                                # us / eu
</project_context>

```

(No `<core_memory>` block — core memory is dropped for the sandbox runtime. See `TODO.md`.)

Total composed size with all sections present: ~8-10 KB. Without plan-mode and SQL-tool-description prose (which lives on the tool, not in the prompt): ~6-8 KB. This compares to today's ~13 KB system prompt; a meaningful reduction, from dropping core memory + modes + contextual-tools-reminder + execution-capabilities blocks.

### 6.3 Pre-interpolation of dynamic variables

All Mustache `{{{var}}}` placeholders get resolved at Run-create time and concatenated into a Python string (no template engine needed at the sandbox boundary). The resolution map:

| Slot | Source | Resolution call |
|---|---|---|
| `{{{role}}}` | constant | inline |
| `{{{tone_and_style}}}` | constant | inline |
| `{{{writing_style}}}` | constant | inline |
| `{{{proactiveness}}}` | constant | inline |
| `{{{basic_functionality}}}` | constant + `{{groups_prompt}}` interpolation | inline with `_format_groups_prompt(team)` |
| `{{groups_prompt}}` | dynamic | `await context_manager.get_group_names()` then `ROOT_GROUPS_PROMPT` if non-empty (same as today's `AgentPromptBuilderBase.get_prompts`). |
| `{{{slash_commands}}}` | constant (edited) | inline |
| `{{{doing_tasks}}}` | constant (edited) | inline |
| `{{{product_advocacy}}}` | constant | inline |
| `{{{tool_usage_policy}}}` | constant (edited) | inline |
| `{{{chat_plan_mode}}}` / `{{{chat_onboarding_task}}}` / `{{{planning_task}}}` / `{{{switching_to_execution}}}` | constants | inline, gated on `permission_mode == "plan"` |
| `{{{switching_to_plan_rewritten}}}` | constant | inline, gated on `feature_flag_snapshot.has_plan_mode_feature_flag` and `permission_mode != "plan"` |
| `{{{billing_context}}}` | dynamic | `await _resolve_billing_context(team, user)` — same logic as today's `BillingPromptMixin._get_billing_prompt`. |
| `{{{project_name}}}` | dynamic | `team.name` |
| `{{{project_timezone}}}` | dynamic | `team.timezone` |
| `{{{region}}}` | dynamic | from settings (`SITE_URL` derivation) |
| ~~`{{{core_memory}}}`~~ | **dropped** | n/a — core memory is removed from the sandbox runtime. |

The resolution pattern in the function body:

```python
async def build_posthog_ai_system_prompt(team, user, *, permission_mode, context_summary, feature_flag_snapshot):
    flags = feature_flag_snapshot or await _snapshot_flags(team, user)
    context_manager = AssistantContextManager(team=team, user=user)

    billing_prompt, group_names = await asyncio.gather(
        _resolve_billing_context(team, user, context_manager),
        context_manager.get_group_names(),
    )

    groups_prompt = (
        format_prompt_string(ROOT_GROUPS_PROMPT, groups=", ".join(group_names))
        if group_names else ""
    )

    basic_functionality = format_prompt_string(
        BASIC_FUNCTIONALITY_PROMPT_REWRITTEN,
        groups_prompt=groups_prompt,
    )

    parts: list[str] = []
    parts.append(f"<identity>\n{ROLE_PROMPT}\n</identity>")
    parts.append(TONE_AND_STYLE_PROMPT)
    parts.append(WRITING_STYLE_PROMPT)
    parts.append(PROACTIVENESS_PROMPT)
    parts.append(f"<capabilities>\n{basic_functionality}\n</capabilities>")
    parts.append(_build_capabilities_by_domain(flags))
    parts.append(SLASH_COMMANDS_PROMPT_REWRITTEN)
    parts.append(DOING_TASKS_PROMPT_REWRITTEN)
    parts.append(PRODUCT_ADVOCACY_PROMPT)
    parts.append(TOOL_USAGE_POLICY_PROMPT_REWRITTEN)

    if permission_mode == "plan":
        parts.append(_build_plan_mode_block())
    elif flags.has_plan_mode_feature_flag:
        parts.append(_build_plan_mode_hint_block())

    parts.append(f"<billing_context>\n{billing_prompt}\n</billing_context>")
    parts.append(_build_project_context_block(team, context_summary))
    # No <core_memory> block — dropped from the sandbox runtime.

    return "\n\n".join(p.strip() for p in parts if p.strip())
```

(Pseudocode only — the actual implementation will use named helpers in the same module.)

### 6.4 Snapshot testing

The composed prompt is the most stable surface in the migration. Snapshot tests catch unintended drift.

**Test file:** `posthog/ee/hogai/chat_agent/test/test_sandbox_prompt.py`.

**Coverage matrix (parameterized — per project convention to use `parameterized`):**

| Test | `permission_mode` | Team configuration | Flags |
|---|---|---|---|
| baseline default mode | `"default"` | groups: `["organization", "instance"]`; core memory: empty; billing: with access | `has_plan_mode_feature_flag=True` |
| baseline plan mode | `"plan"` | as above | as above |
| no groups | `"default"` | groups: `[]`; core memory: empty | as above |
| with core memory | `"default"` | groups: as above; core memory: 500 chars | as above |
| billing — no access | `"default"` | as above; user not admin | as above |
| billing — error | `"default"` | as above; no billing context fetched | as above |
| no plan-mode flag | `"default"` | as above | `has_plan_mode_feature_flag=False` |
| acceptEdits permission mode | `"acceptEdits"` | as above | as above |
| bypassPermissions mode | `"bypassPermissions"` | as above | as above |

Snapshot the full composed string. Use `pytest-snapshot` or `syrupy`. Snapshots live in `posthog/ee/hogai/chat_agent/test/__snapshots__/test_sandbox_prompt.ambr` (or equivalent).

**What we DON'T snapshot:** any segment that's already snapshot-tested in `posthog/ee/hogai/chat_agent/test/test_prompt_builder.py`. The new tests cover the *composition*; the existing tests cover the *constants*.

**Diff-review policy:** snapshot updates require AI-team review. Add a CODEOWNERS line for `posthog/ee/hogai/chat_agent/test/__snapshots__/` pointing at the AI team.

---

## 7. A/B testing and rollout

### 7.1 Feature flag

Reuse the `posthog-ai-sandbox` flag from `00_OVERVIEW.md` § 9 — boolean, per-user, default `false`. When the user has the flag:

1. Conversation create stamps `agent_runtime = 'sandbox'` on the row (`02_CORE.md` § 2).
2. `/conversations/stream/` branches into the sandbox adapter (`02_CORE.md` § 3) which creates Task + Run.
3. The adapter calls `build_posthog_ai_system_prompt(...)` to build `systemPrompt` for the `POST /tasks/{id}/run/` body.
4. `--mcpServers` includes `posthog-data`, `posthog-notebook` (+ optional `posthog-tasks`, `posthog-code` if their per-tool flags are on).
5. **The frontend is unchanged** — `scenes/max/` renders both runtimes; the adapter difference is invisible above `/conversations/*`.

When the user doesn't have the flag: today's LangGraph stack is unchanged.

A second tier of flags (`posthog-ai-sandbox-tools-{slug}` — one per MCP server) lets us roll tools out incrementally during Phase 4. The build function reads them via `feature_flag_snapshot` and gates the "capabilities by domain" section accordingly.

### 7.2 Eval acceptance criteria

Before flipping the flag for any internal user, the new prompt must pass the AI team's existing eval suite at parity with today's. The relevant evals live in [`ee/hogai/eval/`](../../posthog/ee/hogai/eval/). At a minimum:

| Eval | Pass criterion |
|---|---|
| Insight creation eval | ≥ 95% of today's success rate; no regression in tool-selection correctness. |
| SQL generation eval | ≥ today's pass rate. Function casing and person_id join rules must be respected at ≥ today's frequency (these moved from system prompt to tool description; the test confirms the model still picks them up). |
| Dashboard generation eval | ≥ today's. |
| Error-tracking triage eval | ≥ today's. |
| Plan-mode eval | ≥ today's pass rate. With option C, "plan mode" is `permission_mode === "plan"` + the addendum prompt — confirm the model still completes the clarify → finalize_plan → request approval → switch arc. |
| Mode-routing eval (NEW) | Given a user question that today triggers a `switch_mode("sql")`, with the new prompt the model should call `posthog_data_execute_sql` directly. ≥ 90% accuracy. |
| Slash command eval | `/init`, `/remember`, `/usage`, `/feedback`, `/ticket` — confirm the model continues to interpret them correctly. (Note: most are routed by the frontend before they hit the agent, so this is a degenerate test.) |

In addition, run a 100-user beta with internal employees for two weeks, capturing:

- User-reported confusion ("I asked for X and got Y" reports) — should be ≤ today's rate.
- Token usage per chat — should be roughly equal or better.
- Cold-start latency — Run-create + first-message should be ≤ 8 seconds at p95 (sandbox boot is the bottleneck; the prompt-build call itself is < 200 ms with `feature_flag_snapshot` shared).

If any eval misses, do not flip. Tune the prompt or the tool descriptions and re-run.

### 7.3 Decommission plan

After 30 days at 100% rollout with no incidents:

1. Delete `posthog/ee/hogai/chat_agent/prompts/` (the LangGraph prompt directory).
2. Delete `posthog/ee/hogai/chat_agent/prompt_builder.py`.
3. Delete `posthog/ee/hogai/chat_agent/mode_manager.py` (modes don't exist anymore).
4. Delete `posthog/ee/hogai/chat_agent/toolkit.py` (tools are MCP servers now).
5. Delete `posthog/ee/hogai/core/agent_modes/presets/*.py` (modes don't exist).
6. Delete `posthog/ee/hogai/tools/switch_mode.py`, `finalize_plan/`, `create_form.py` (replaced).
7. Delete `posthog/ee/hogai/chat_agent/sql/` (HogQL generator moves to tool descriptions + MCP resources).
8. Keep `posthog/ee/hogai/context/` — `01_CONTEXT.md` still uses `_format_ui_context`'s template logic (ported to TypeScript).

The new prompt module `posthog/ee/hogai/chat_agent/sandbox_prompt.py` survives. The `posthog/ee/hogai/tools/` directory survives only for tools that have both an MCP and a LangGraph entry-point during the transition — once decom is done, each tool exports only its MCP-adapter implementation.

Document the deletion plan in a tracking issue. Tag the AI team.

---

## 8. Open questions

1. **Cloud-prompt extras opt-out.** Should we add `--no-cloud-prompt-extras` (or `--cloud-prompt-mode=posthog_ai`) to the agent-server to short-circuit the No-Repository-Mode block when running in PostHog AI? Pro: ~1 KB token savings per Run. Con: agent-server fork point. Recommendation: do it post-MVP if usage data shows the dead-weight matters. *Owner: AI + agent-server.*
2. **Plan-mode UX.** Option C maps "plan mode" to ACP `permission_mode === "plan"`. The UI affordance today (`PlanModeBanner` in `scenes/max/`) needs to wire to `_posthog/mode_change` notifications instead of the LangGraph-emitted plan-mode signal. Confirm `03_RICH_UI.md` is aware. *Owner: AI + frontend.*
3. **TodoWrite: built-in or `posthog-tasks`?** Claude Code's built-in `TodoWrite` is close enough — but it doesn't persist across Runs. PostHog AI today persists todos with the conversation. If we want cross-Run persistence (which `02_CORE.md`'s Task-as-conversation model wants), we need our own `posthog-tasks` MCP. *Owner: AI.*
4. **Slash command routing.** `/init`, `/remember`, `/usage`, `/feedback`, `/ticket` — `02_CORE.md` § 8 owns the routing decision. The prompt content (`SLASH_COMMANDS_PROMPT`) survives as-is, but if any command no longer exists, edit accordingly. *Owner: AI + frontend.*
5. **HogQL prompt placement.** Inlining the 36 KB SQL prompt into the `execute_sql` tool description means every tool-call invocation hits a ~36 KB prompt-cache page. Acceptable if Claude's prompt-cache handles it (it should — same key per tool call). Alternative: split function-casing + person_id rules into the description (~1 KB), expose the rest as MCP resources (`schema://hogql/functions`, etc.) — agent fetches once and caches in conversation context. Recommendation: split. Confirm with AI team — the split needs eval validation. *Owner: AI.*
6. **MCP framework auth.** All remote MCP servers need to validate the sandbox JWT and extract `team_id` + `user_id`. The current `services/mcp/` framework already handles this for the existing PostHog MCP tool — confirm the new servers use the same middleware. *Owner: backend.*
7. **Feature-flag snapshot freshness.** `feature_flag_snapshot` is captured at Run-create. If flags toggle mid-Run, the user sees stale prompt behavior until the next Run. Acceptable today (Anthropic's prompt caching makes per-turn re-evaluation expensive). Confirm this is the policy we want. *Owner: AI.*
8. **Backward-compatible `switch_mode` sunset.** During the rollout window, some in-flight conversations will reference `switch_mode` in their message history. The new agent doesn't have that tool. The cleanest handling: do nothing — the model won't call a tool it doesn't see. The model may *say* it would switch modes; that's verbal-only narration. Acceptable. *Owner: AI.*
9. **Region-specific copy.** `<project_context>` carries `region` (US/EU). Is there any region-specific copy we should inject (e.g. data residency reminders for EU, links to region-specific docs)? *Owner: AI + product.*
10. **Web search tool placement.** Today, `web_search` is gated behind "no Bedrock primary" (`toolkit.py:147-151`). The same gating applies in the sandbox — Bedrock-routed sandboxes shouldn't expose `web_search`. Where does this decision live? Recommend: at Run-create, the Task-create endpoint inspects the LLM gateway routing for the team and conditionally omits `web_search` from `--mcpServers` (it's a Claude built-in, but it can be disabled). *Owner: AI.*
11. **`{{{onboarding_task}}}` migration.** `CHAT_ONBOARDING_TASK_PROMPT` describes when to ask clarifying questions via `create_form`. `create_form` is a client-side tool (`03_RICH_UI.md` § 4). The system prompt mentions it; the tool is registered by the frontend via `usePostHogAiTool`; the model must see it in the tool list to call it. Confirm with `03_RICH_UI.md` that `create_form` is always registered. *Owner: AI + frontend.*
12. **Per-mode todo examples.** Today's per-preset `POSITIVE_TODO_EXAMPLES` (dashboard-creation, SQL-with-segmentation, churn analysis, multi-metrics) → move to `TodoWrite`'s description. But Claude Code's built-in description isn't ours to author. Resolution depends on Q3 (built-in vs `posthog-tasks`). If we go with the built-in, the examples either disappear or move into `BASIC_FUNCTIONALITY_PROMPT`/`DOING_TASKS_PROMPT` (which inflates the system prompt). *Owner: AI.*
13. **Permission-mode default for PostHog AI.** Today's Max defaults to "behave as if `acceptEdits` for write tools" (we have `DangerousOperationApprovalCard`). The sandbox default is `"bypassPermissions"` for Claude (`CLOUD_AGENTS_FRONTEND_SPEC.md` § 10.5). Setting `state.initial_permission_mode = "default"` (which surfaces all permissions through `permission_request`) restores today's behavior. Confirm with AI which we want. *Owner: AI + product.*
14. **Group-name truncation.** `ROOT_GROUPS_PROMPT` interpolates the team's group type names. If a team has many groups (some have 10+), the list is short but it's possible they've configured human-friendly names that are long. Truncate per-name at, say, 64 chars? Defer to AI team.
15. **Documentation.** Today's `posthog/ee/hogai/PROMPTING_GUIDE.md` describes prompt conventions for the LangGraph stack. Either update it for the sandbox model or split into two docs (LangGraph legacy + sandbox new). *Owner: AI.*
