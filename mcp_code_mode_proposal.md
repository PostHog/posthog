# PostHog MCP: Code Mode and Fast Mode proposal

Status: proposal / design spec.
Scope: `services/mcp/` (the Hono MCP runtime and the `posthog-cli api` agent CLI), the 56 `products/*/mcp/tools.yaml` catalogs, and the backend execution environments a server-side code runtime could reuse.

Every number below comes from the repository at the time of writing, measured with the scripts in [Appendix A](#appendix-a-how-the-numbers-were-measured).
Token counts use the same 4-characters-per-token heuristic as `services/mcp/src/lib/estimate-tokens.ts`, so they are estimates, not tokenizer output.
Production latency and turn counts are not in the repository. Where they matter, this doc names the `$mcp_tool_call` query that produces them instead of guessing.

---

## TL;DR

- The catalog has **1,034 tools across 72 categories**. Advertised in full, their definitions cost about **1.07M tokens** (827k of it input schemas). No client can take that, which is why CLI mode (`exec`) is already the default for every client except Cursor.
- CLI mode already solves the _context bloat_ problem: the upfront cost is roughly **9k tokens** (tool description, command reference, instructions). It does not solve the _round-trip_ problem. Discovery, schema lookup and each call are separate model turns, `exec` rejects batched commands by design, and every fetch → filter → act loop runs through the model one item at a time.
- The repository already contains most of what a Code Mode needs: typed zod schemas for every tool, a single validation and dispatch path inside `exec`, per-inner-call analytics, a signed two-step confirmation runtime, and a local CLI that runs the same `exec` in-process.
- The missing part is an **`execute_code` verb that runs model-written TypeScript in an isolate inside the Hono process**, where the only capability is a generated `ph` SDK whose methods dispatch through the existing `exec call` pipeline. The isolate never sees a credential.
- **Fast Mode** is that runtime offered as a paid tier: warm isolates, higher inner-call and rate budgets, larger result budgets and parallel fan-out. Since most MCP clients bring their own model, Fast Mode bills **sandbox compute and inner API calls**, not model tokens. Model tiers matter only on PostHog-hosted agent surfaces.
- One finding needs action whatever happens to this proposal. In MCP mode, `exec` is advertised with `destructiveHint: false`, and only the CLI turns on `requireDestructiveConfirmation`. So the client's own approval prompt never fires for the 130 destructive tools reached through `exec` (the 14 `-prepare`/`-execute` pairs are the exception). See [§1.6](#16-safety-gap-found-during-the-audit).

---

## 1. Current state topology

### 1.1 Where the MCP code lives

| Layer              | Path                                                                                           | Role                                                                                                                                                                                                                                              |
| ------------------ | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Edge router        | `services/mcp/src/index.ts`, `src/proxy.ts`                                                    | Cloudflare Worker: OAuth metadata, token validation, region resolution, proxy of `/mcp` to Hono                                                                                                                                                   |
| Protocol runtime   | `services/mcp/src/hono/`                                                                       | Node/k8s. `dispatcher.ts` (JSON-RPC, legacy and 2026-07-28 stateless dialects), `tool-executor.ts` (`tools/list`, `tools/call`), `tool-catalog.ts` (warm catalog), `request-state-resolver.ts` (per-request mode, scopes, flags, filtered roster) |
| Meta-tool          | `services/mcp/src/tools/exec.ts` (2,060 lines)                                                 | The `exec` tool: `tools`, `search`, `info`, `schema`, `call`, `learn`                                                                                                                                                                             |
| Search             | `services/mcp/src/tools/tool-search.ts`                                                        | Regex predicate plus field-weighted token ranking (name 3, title 2, description 1)                                                                                                                                                                |
| Tool definitions   | `products/*/mcp/tools.yaml` (56 files), `services/mcp/definitions/*.yaml`                      | YAML source of truth: title, description, scopes, annotations, feature flags                                                                                                                                                                      |
| Codegen            | `services/mcp/scripts/generate-tools.ts`, `generate-orval-schemas.mjs`                         | YAML plus OpenAPI → `src/tools/generated/*.ts` (zod schemas and handlers), `src/generated/<product>/api.ts`, `src/api/generated.ts` (118,669 lines of typed client)                                                                               |
| Hand-written tools | `services/mcp/src/tools/{insights,featureFlags,experiments,…}`                                 | 57 tools where codegen is not enough (they win on name collision, `mergeToolFactories.ts`)                                                                                                                                                        |
| Confirmation       | `src/tools/confirmed-action-runtime.ts`, `src/lib/signed-state`                                | Two-tool `-prepare`/`-execute` flow with a signed hash and a single-use nonce in Redis                                                                                                                                                            |
| Instructions       | `src/hono/instructions.ts`, `src/lib/instructions-formatter.ts`, `src/templates/sections/*.md` | Per-mode server instructions and the `exec` command reference                                                                                                                                                                                     |
| Local runtime      | `services/mcp/src/cli/`                                                                        | `posthog-cli api …`: the same `createExecTool` run in-process on the user's machine                                                                                                                                                               |
| Evals              | `services/mcp/evals/`                                                                          | Benchmark v2 (`tasks.yaml`), probe and agent modes, scores tokens per task, retries and p50/p95                                                                                                                                                   |

### 1.2 Mode selection per client

`resolveMode()` in `src/hono/request-state-resolver.ts:69` picks the mode: an explicit `?mode=` or `x-posthog-mcp-mode` wins, then `clientProfile.isToolsModeClient()`, else `cli`.

| Client                     | Detected by                                                        | Mode                           | Notes                                                                                                                                                                    |
| -------------------------- | ------------------------------------------------------------------ | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Claude Code                | `claude-code` in `clientInfo.name`                                 | `cli` (single `exec`)          | Inline exec UI-app host (`INLINE_EXEC_UI_APP_VENDOR_FRAGMENTS`)                                                                                                          |
| Claude web/desktop, Cowork | `claudeai`, `cowork`                                               | `cli` plus `render-ui`         | The only hosts that get `learn` guides. Claude chat hosts never show `instructions` to the model, so the domain index moves into the command reference                   |
| Cursor                     | `cursor` in client name or UA (`TOOLS_MODE_CLIENT_NAME_FRAGMENTS`) | `tools` (full filtered roster) | The only tools-mode client                                                                                                                                               |
| Codex                      | `codex` in name, or `openai-mcp/… (Codex)` UA                      | `cli`                          | `supportsInstructions: false` (`client-detection.ts:228`), so Codex never sees the server instructions and works from the `exec` description and command reference alone |
| Other coding agents        | `CODING_AGENT_CLIENT_NAME_FRAGMENTS`                               | `cli`                          |                                                                                                                                                                          |

### 1.3 Tool count and categories

Source: `services/mcp/schema/tool-definitions-all.json` (generated by `hogli build:openapi`).

- **1,034 tools** in **72 categories**.
- **550** read-only (`readOnlyHint`), **130** destructive (`destructiveHint`), **354** non-destructive writes.
- **286** sit behind a feature flag, 25 behind a feature entitlement, 20 require AI consent.
- **14** `-prepare`/`-execute` confirmed-action pairs.
- By name shape: 177 list, 192 get/retrieve, 166 create, 100 update, 67 delete/destroy, 33 `query-*` wrappers, 48 run/execute/prepare/search, 251 other verbs.

The table maps the categories to the domains in the brief.
"Tokens" is the full `tools/list` entry (name, title, description, input schema, annotations) summed over the category.

| Domain (brief)                | Categories in the catalog                                                                                                                                                                                                                                                                                     | Tools | Read-only | Destructive | ≈ Tokens | Avg tokens/tool |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----: | --------: | ----------: | -------: | --------------: |
| Analytics / insights          | Query wrappers, Product analytics, Web analytics, Dashboards, Insights & analytics, SQL, Events & properties, Data schema, Actions, Annotations, Marketing analytics, Customer analytics, Metrics                                                                                                             |   158 |        81 |          19 |     401k |           2,540 |
| Feature flags                 | Feature flags, Early access features                                                                                                                                                                                                                                                                          |    34 |        16 |           5 |      18k |             536 |
| Experiments                   | Experiments                                                                                                                                                                                                                                                                                                   |    43 |        18 |           5 |      65k |           1,522 |
| Session replay                | Session replays, Replay vision                                                                                                                                                                                                                                                                                |    66 |        33 |           9 |      37k |             558 |
| Cohorts                       | Cohorts                                                                                                                                                                                                                                                                                                       |     6 |         2 |           0 |       4k |             675 |
| Person management             | Persons                                                                                                                                                                                                                                                                                                       |     7 |         4 |           1 |       1k |             191 |
| Data pipelines / batch export | Data pipelines, Functions, Function templates, Workflows, Warehouse sources, Data warehouse, Data quality, Managed migrations, Messaging                                                                                                                                                                      |   124 |        57 |          22 |      78k |             628 |
| Site apps / platform          | Platform Features, Canvas, Streamlit apps, Notebooks, Endpoints, Reverse proxy                                                                                                                                                                                                                                |    98 |        57 |           9 |      43k |             435 |
| Settings / billing / access   | Billing, Billing alerts, Access control, Organization & project management, Core, Integrations                                                                                                                                                                                                                |    55 |        39 |           9 |      39k |             707 |
| Observability                 | Error tracking, Error tracking alerts, Logs, Tracing, AI observability, Alerts, Health                                                                                                                                                                                                                        |   157 |        84 |          20 |     210k |           1,338 |
| Agent / AI surfaces and other | Signals, Tasks, Skills, Data catalog, MCP analytics, PostHog AI, Context wiki, Business knowledge, Conversations, User interview topics, Visual review, Stamphog, ReviewHog, Field notes, Reminders, Subscriptions, Surveys, Engineering analytics, MCP registry, MCP Store, Docs, Utilities, Feedback, Debug |   286 |       159 |          31 |     176k |             616 |

Size distribution: median tool **299** tokens, p90 **1,687**, max **43,565**.
Six categories (Query wrappers, Marketing analytics, Error tracking, Experiments, Signals, Logs) hold about half the bytes.
The largest single entries are schemas for rich query objects:

| Tool                                         | ≈ Tokens |
| -------------------------------------------- | -------: |
| `marketing-analytics-create-conversion-goal` |   43,565 |
| `marketing-analytics-update-conversion-goal` |   42,626 |
| `query-trends`                               |   28,234 |
| `experiment-update`                          |   27,074 |
| `query-trends-actors`                        |   25,283 |
| `query-funnel`                               |   24,700 |
| `query-retention`                            |   21,473 |
| `project-settings-update`                    |   18,072 |

The 12 "Query wrappers" tools alone cost **218k tokens**, an average of 18k each.

### 1.4 Token bloat: tools mode vs CLI mode

| Surface                                        | What is in context before the first call                                 |  ≈ Tokens |
| ---------------------------------------------- | ------------------------------------------------------------------------ | --------: |
| Tools mode, entire catalog                     | 1,034 entries                                                            | 1,073,000 |
| Tools mode instructions                        | `buildToolsInstructions` with every tool                                 |     7,500 |
| CLI mode `exec` description                    | `buildExecToolDescription`                                               |       330 |
| CLI mode command reference (default)           | `buildExecCommandReference`, which inlines domain and query-tool indexes |     8,200 |
| CLI mode command reference (Claude chat hosts) | `buildClaudeExecCommandReference` (domain index moved into `learn`)      |     3,300 |
| CLI mode instructions                          | `buildExecInstructions`                                                  |       365 |

So CLI mode cuts upfront context by about two orders of magnitude.
The cost moves to per-call payloads:

- `search` returns at most 25 names (`MAX_RANKED_SEARCH_RESULTS`). A plain-word query matches loosely: `create dashboard insight` matches **354** tools before truncation.
- `info` returns the full JSON Schema up to `TOKEN_CHAR_LIMIT` (48,000 characters, about **12k tokens**). Above that it returns a summary with `hint`s, and the agent _must_ call `schema <tool> <field>` for each hinted field. The instructions say this is required. For `query-trends`, that means several extra turns before the first real call.
- `call` results have no size cap in `exec`. List tools return whatever page size the API returns (TOON- or YAML-formatted by `formatResponse`), and that whole page enters the model context.

Tools mode (Cursor) receives the roster filtered by scopes, flags, `?features=` and `excludeTools`, but it gets no search and no lazy schema.
The query-wrapper and marketing schemas alone exceed most practical tool budgets.

### 1.5 Tool search overhead

Search itself is cheap. It runs in-process over the warm catalog (`ToolCatalog.warmup()`, measured at about 10 s cold in the test harness, done once per pod):

| Operation over 1,034 tools                   | Mean server time |
| -------------------------------------------- | ---------------: |
| `searchToolsRanked` (natural-language query) |           3.1 ms |
| `searchToolsRegex` (`feature-flag`)          |           0.8 ms |

The real overhead is **model turns, not server milliseconds**.
Each `exec` verb is one full model round trip: the whole context is re-read, then output is generated.
A first-time task takes at least `search → info → call` (3 turns), plus one `schema` turn per hinted field.
To get the production distribution of turns per task, group `$mcp_tool_call` events by `mcp_conversation_id` and look at the sequence of `exec_verb` values (`ExecCommandMeta` in `exec.ts:158`).
`query-mcp-tool-neighbors` and `query-mcp-tool-stats` already expose the building blocks.

### 1.6 Safety gap found during the audit

- `EXEC_TOOL_ANNOTATIONS` (`exec.ts:44`) sets `destructiveHint: false`. The reason is deliberate: Claude Code prompts on every call to a destructive tool, and every read also goes through `exec`.
- The `--confirm` check (`exec.ts:1830`) runs only when `requireDestructiveConfirmation` is set. Only `src/cli/index.ts:79,99` sets it. The Hono path never does.
- Result: over MCP, a model can call any of the 130 destructive tools through `exec call` with no client prompt and no `--confirm`. Only the 14 confirmed-action pairs are protected, because their gate is inside the tool.

Recommendation: turn on `requireDestructiveConfirmation` for the Hono `exec` behind a flag, and measure the `needs_confirmation` error rate.
This is PR 1 in the roadmap, and a precondition for Code Mode: code must never become a faster way around this gate.

### 1.7 Multi-turn failure points

Each item below is visible in the code as a dedicated recovery path. That code exists because agents hit these failures often enough to justify it.

| #   | Failure point                                                                                                         | Evidence                                                                                                                         | Clients hit                                                                           |
| --- | --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| F1  | **One command per request.** Agents stack `search` + `info` + `call` in one `exec`, and the whole request is rejected | `splitBatchedCommands`, `batched_command` reason, "One command per request" in `schema/exec-command-reference.md`                | All CLI-mode clients                                                                  |
| F2  | **Schema guessing.** The agent calls without `info`, or skips the `schema` drill-down on a hinted field               | `formatInputValidationError`, `missingParameterHint`, `describeUnionIssue` in `exec.ts` (≈700 lines of validation-error shaping) | All; worst on Codex, which never sees the instructions telling it to run `info` first |
| F3  | **Flattened or over-wrapped arguments.** Nested payloads sent flat, or wrapped one level too deep                     | `rewrapFlattenedArguments`, `looksLikeUnwrappedPayload`, `overWrappedPayloadKey`                                                 | All                                                                                   |
| F4  | **JSON-encoded strings in place of objects**                                                                          | `SURVEY_WRITE_RECOVERY_HINT` in `lib/tool-error-hints.ts`                                                                        | Clients that stringify arguments whose generated schema is empty                      |
| F5  | **Oversized queries retried as-is.** Logs queries time out, and the agent retries the same call                       | `LOGS_QUERY_RECOVERY_HINT` ("Many cheap count calls beat one broad `query-logs`")                                                | All                                                                                   |
| F6  | **N+1 transformations.** List → iterate → get/act per item → filter → summarize, one model turn per item              | Structural: 177 list tools, 192 get tools, no batch or iterate verb, and `exec` refuses batches                                  | All; the main cost driver                                                             |
| F7  | **Stale or renamed tools**                                                                                            | `flagGatedToolMessage`, `superseded_by` (6 tools), `redirect_hint`, the `read-data-warehouse-schema` → `execute-sql` redirect    | All                                                                                   |
| F8  | **Scope-gated misses** read as "tool missing"                                                                         | `scope_gated_matches` hint in `search`                                                                                           | OAuth clients with narrow scopes                                                      |
| F9  | **Roster overflow in tools mode**                                                                                     | 1.07M tokens unfiltered, query wrappers at 18k each                                                                              | Cursor                                                                                |
| F10 | **No instructions**                                                                                                   | `supportsInstructions: false`                                                                                                    | Codex                                                                                 |

F1, F2, F3 and F6 all come from making the model drive a data transformation one step at a time through a string protocol.
Code Mode targets exactly that.

---

## 2. Proposed Code Mode architecture

### 2.1 Principle

Code Mode is **not** a second tool system.
It is a new front end on the existing dispatch path:

```text
model-written TS ──► isolate ──► ph.<domain>.<op>(args) ──► host binding
                                                              │
                     same code path as `exec call <tool> <json>`:
                     findTool → scope/flag gates → confirmation gate →
                     zod safeParse (+ rewrapFlattenedArguments) →
                     handler → ApiClient (token, region, team) →
                     trackInnerCall ($mcp_tool_call per inner call)
```

The isolate holds no token, has no network, no filesystem and no timers beyond a bounded `sleep`.
Everything it can do is a `ph.*` call, and each `ph.*` call is exactly one validated `exec call`.
So scopes, feature flags, read-only mode, staff-only filtering, rate limits, audit headers (`X-Posthog-Mcp-Session-Id`, `-Conversation-Id`) and analytics all carry over unchanged.

### 2.2 The SDK module the model sees

Generate it from the sources `generate-tools.ts` already reads: the YAML definitions plus the per-tool zod schemas.
There is no hand-maintained surface.

Shape (excerpt of generated `posthog-sdk.d.ts`):

```ts
/** PostHog SDK available inside execute_code. Every method is one validated API call. */
declare namespace ph {
  /** Feature flags. Scopes: feature_flag:read / feature_flag:write */
  namespace featureFlags {
    /** List feature flags in the active project. Read-only. */
    function list(args?: {
      search?: string
      active?: 'true' | 'false' | 'STALE'
      limit?: number
      offset?: number
    }): Promise<Page<FeatureFlag>>
    /** Get one flag by id. Read-only. */
    function get(args: { id: number }): Promise<FeatureFlag>
    /** Update a flag. Write: counts against the run's write budget. */
    function update(args: { id: number } & Partial<FeatureFlagPatch>): Promise<FeatureFlag>
    // delete is not exposed: destructive, tool-call only (see §2.4)
  }
  namespace query {
    /** Run HogQL. Prefer this for aggregation over paging raw rows. */
    function sql(args: { query: string; limit?: number }): Promise<SqlResult>
    function trends(args: TrendsQuery): Promise<TrendsResult>
    // …
  }
  /** Pages through a list method, bounded by maxItems (default 1,000). */
  function paginate<T>(
    fn: (a: { limit: number; offset: number }) => Promise<Page<T>>,
    opts?: { maxItems?: number }
  ): AsyncIterable<T>
  /** Record a call that must go through a normal tool call (destructive, billing, credentials). */
  function requireToolCall(tool: string, args: unknown, reason: string): never
  /** Return value shown to the model; everything else stays in the sandbox. */
  function output(value: unknown, opts?: { format?: 'toon' | 'json' | 'markdown' }): void
}
```

Rules for generation:

- **Naming.** The namespace comes from the YAML `feature` (`feature_flags` → `featureFlags`). The method comes from the tool name minus the feature prefix (`feature-flag-get-all` → `list`), with an override key in `tools.yaml` for collisions. `scripts/lint-tool-names.ts` already enforces the naming regularity this depends on.
- **Types.** Emit TypeScript from zod with `io: 'input'`, matching what `info` shows (`exec.ts`, the `info` case). Share response types from `src/api/generated.ts` where Orval has them. Otherwise emit `unknown`, with the TOON/YAML formatter off inside the sandbox, because code wants raw JSON.
- **Docs.** The first line of the tool description becomes JSDoc. The full description stays behind `info`.
- **Delivery to the model, lazily, in the same spirit as `exec`:**
  - The `exec` description gains one line: "`run <typescript>` executes code against the `ph` SDK; `types <domain>` shows its signatures."
  - `types` with no argument returns the domain index: 72 lines, about 1.5k tokens.
  - `types featureFlags` returns that namespace's `.d.ts`. Signatures without the full descriptions should come to roughly 30–50% of the JSON Schema sizes in §1.3. Validate this in PR 3.
  - The query wrappers are the exception. `TrendsQuery` and friends are the 20k+ token schemas, so `types query` emits a summarized interface with the same `hint`-driven drill-down (`schema-utils.ts`), and code should prefer `ph.query.sql` for anything HogQL can express.

### 2.3 The `execute_code` wrapper

Surface it as a new `exec` verb, not a new MCP tool, so `tools/list` stays one entry and clients that pin tool lists need no change:

```text
run [--timeout <ms>] [--dry-run] <typescript source>
```

A standalone `execute_code` MCP tool with `{ code, timeout_ms, dry_run }` is also advertised when `?mode=code` is set, for clients that handle a large string argument better than a CLI string.
Both routes share one implementation.

Execution contract:

| Aspect                        | Standard (`run`)                                                              | Fast Mode                                                |
| ----------------------------- | ----------------------------------------------------------------------------- | -------------------------------------------------------- |
| Language                      | TypeScript, type-stripped (esbuild is already a dependency) and run as ES2023 | same                                                     |
| Isolate                       | Fresh context per run                                                         | Context from a warm per-pod pool, SDK stubs pre-compiled |
| Wall time                     | 15 s                                                                          | 60 s                                                     |
| CPU time                      | 5 s                                                                           | 20 s                                                     |
| Memory                        | 64 MB                                                                         | 256 MB                                                   |
| Inner `ph.*` calls            | 50                                                                            | 500                                                      |
| Inner-call concurrency        | 4                                                                             | 16                                                       |
| Write calls (non-destructive) | 10, and 0 when the connection is read-only                                    | 100                                                      |
| `ph.output` size to model     | 8k tokens                                                                     | 32k tokens (truncated with a notice)                     |

The limit values are starting points to tune with evals, not measured optima.

Every run returns one envelope:

```json
{
  "status": "ok | error | requires_tool_call | budget_exceeded",
  "output": "...formatted ph.output() value...",
  "calls": [{ "tool": "feature-flag-get-all", "ms": 212, "ok": true }, "..."],
  "writes": [{ "tool": "feature-flag-update", "target": "flag:1234", "ok": true }],
  "error": { "kind": "...", "message": "...", "user_frames": ["run.ts:14:7 ..."], "failing_call": { "tool": "...", "args_digest": "..." } },
  "fallback": { "...see §2.5..." },
  "usage": { "wall_ms": 1840, "cpu_ms": 310, "inner_calls": 23 }
}
```

`calls` is capped and summarized when it is long.
`writes` is always complete, so the model and the user can see every mutation the script made.
In `--dry-run`, write methods validate and return a synthetic result, and `writes` lists what _would_ have happened.
This is the same idea as `posthog-cli api call --dry-run`.

### 2.4 Code Mode suitability matrix

Tiering is declared in YAML (`code_mode: allow | write | deny`) with a default derived from annotations.
A lint rejects `allow` on a destructive tool.

| Tier         | Default for                                                                                                       | Count today | In code                                                                                                              | Examples of prime use                                                                                                                                                                                                                                                                                                                                                                       |
| ------------ | ----------------------------------------------------------------------------------------------------------------- | ----------: | -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A: allow** | `readOnlyHint: true`                                                                                              |         550 | Callable freely within the call budget                                                                               | HogQL plus post-processing (`ph.query.sql` then joins and ranking in TS); multi-step metric math (conversion by cohort by week); cohort iteration (list cohorts → size → overlap); flag hygiene reports (list flags → evaluation counts → stale set); replay triage (list recordings by error → group by URL); experiment readouts across many experiments; error-tracking issue clustering |
| **B: write** | non-destructive writes                                                                                            |         354 | Callable, counted against the write budget, all listed in `writes`, blocked when the connection is read-only         | Bulk tagging, bulk dashboard tile creation, bulk flag rollout edits with a prior dry run, annotations from a computed list                                                                                                                                                                                                                                                                  |
| **C: deny**  | `destructiveHint: true` (130), `-prepare`/`-execute` pairs (28, 7 of them also destructive), plus explicit denies |       ≥ 151 | Not bound. Code can only call `ph.requireToolCall(tool, args, reason)`, which ends the run with `requires_tool_call` | Deletes and destroys, billing and plan changes (`Billing`, `Billing alerts`), access control changes, personal/project API key and integration credential operations, org/project deletion, `tasks-run-create`, staff-only tools, all third-party gateway tools (`<server>__<tool>`) because PostHog cannot know whether they mutate                                                        |

Why third-party gateway tools are denied: `request-state-resolver.ts` already turns them off in read-only mode for this reason. A script calling them in a loop would multiply an unknown risk.

Operations that gain little from code and should stay plain calls:

- Single lookups, where `call` is already one turn.
- `render-ui` and UI-app tools, whose output is for the host, not the model.
- `learn` and skills.
- `docs-search`.

### 2.5 Dual-path prompts and fallback routing

#### Static layer: what the model is told up front

`buildExecToolDescription` and `buildExecCommandReference` gain a short Code Mode section. It is kept in `src/templates/sections/code-mode.md` so the Claude, default and Codex variants share one source:

```text
Use `run` when a task needs more than two calls, a loop, filtering, joins, or arithmetic.
Use `call` for a single lookup, for anything destructive, and whenever a `run` result says
"requires_tool_call" or "fallback". Code sees only the `ph` SDK: no fetch, no env, no fs.
```

Codex gets this through the command reference, because it never sees `instructions` (F10).

#### Dynamic layer: what the sandbox injects on failure

The sandbox classifies every failure and returns a `fallback` block written for the model.
It does not return a bare stack trace:

| `error.kind`            | Trigger                                                                       | Injected fallback instruction                                                                                                                                                            |
| ----------------------- | ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `syntax` / `type_strip` | esbuild fails                                                                 | Line and column of the error, the offending line, "fix and rerun". No mode change                                                                                                        |
| `unsupported_api`       | Code touches `fetch`, `require`, `process`, `import`, or anything not in `ph` | "The sandbox only exposes `ph`. Use `ph.<closest>` (name suggested by `searchToolsRanked` over the identifier), or fall back to `call <tool>`"                                           |
| `unknown_method`        | `ph.x.y` is not bound                                                         | The same `findTool` / `flagGatedToolMessage` / `superseded_by` resolution as `exec call`, rendered as the SDK name plus the tool name                                                    |
| `validation`            | Inner call fails zod                                                          | The output of `formatInputValidationError` for that call (the existing ≈700 lines of shaping), plus the path of `run.ts` that built the arguments                                        |
| `denied_tier_c`         | Code references a tier C method, or calls `ph.requireToolCall`                | `status: requires_tool_call`, with the exact `call --confirm <tool> <json>` to issue next, and the reason                                                                                |
| `api_error` 4xx         | Inner call returns 4xx                                                        | Passed through verbatim, the same as today                                                                                                                                               |
| `api_error` 5xx         | Inner call returns 5xx                                                        | `getToolRecoveryHint` (logs, surveys, …) plus "partial writes: [...]"                                                                                                                    |
| `budget_exceeded`       | Call, write, CPU or wall budget hit                                           | What was consumed, partial `output` so far, "narrow with `ph.query.sql` aggregation or split the run"                                                                                    |
| `runtime`               | Uncaught exception in user code                                               | Stack cut to `run.ts` frames only (host frames removed), plus the last 3 inner calls                                                                                                     |
| `sandbox_unavailable`   | Pool exhausted, flag off, pod draining                                        | "Code Mode is unavailable for this request. Use `search` / `info` / `call`", plus the tool names the script referenced, resolved from its AST, so the model can do the same work by hand |

The fallback text is rendered through the same channel as other informational responses (`POSTHOG_INFORMATIONAL_RESPONSE_KEY`), so it is tagged as server guidance, not data.

#### Session state: when to switch paths

A per-conversation state record lives in Redis next to the existing session keys (`McpSessionRedisStore`), keyed by `mcpConversationId` or `mcpSessionId`:

```text
code_mode_state = { mode: 'code' | 'degraded', failures_by_kind, degraded_until, domains_degraded[] }
```

- Two consecutive `runtime` or `validation` failures in the same domain → mark that domain `degraded` for 10 minutes. Later `run` calls that touch it return `sandbox_unavailable`-style guidance to use `call`.
- `sandbox_unavailable` never counts against the model.
- A `run` that succeeds resets the failure count for that domain.
- Clients that support `notifications/tools/list_changed` also get the `exec` description re-rendered without the Code Mode line while degraded. Everyone else gets the text in results, which works on every client today, the same reasoning `confirmed-action-runtime.ts` gives for not depending on elicitation.

#### Prompt injection through data

Code Mode changes the injection threat model.
Event properties, person properties, recording console logs, survey answers and error messages are **end-user controlled**.
A model that reads them may be persuaded to write a script that mutates at scale.
Mitigations:

1. Tier C is never bound, so no script can delete, change billing, or touch credentials, whatever the model was told.
2. The write budget plus the `writes` list make bulk mutation visible and bounded.
3. In a run that calls no write method, only `ph.output` reaches the model. Raw rows stay in the sandbox, which _reduces_ the injection surface compared to today, where every row enters context.
4. A run whose source both reads end-user-controlled data (`query.*`, `persons.*`, `replay.*`, `errorTracking.*`, `surveys.*` responses) and calls a tier B write in a loop needs `--confirm-writes`. The first attempt returns `requires_tool_call`-style guidance that lists the writes.
5. Inputs from the model's other tools are not treated as trusted either. The tiering is the control, not the prompt.

### 2.6 Why not execute code in the existing `exec call` path directly

- `exec` has a string command grammar. A multi-line script inside it collides with the batch detector (`splitBatchedCommands`), which is why `run` must be parsed before that check.
- A script needs streaming partial results, budgets and cancellation, which the one-shot `call` flow does not model.
- Keeping `run` as its own verb keeps analytics clean: `exec_verb: 'run'`, plus one `$mcp_tool_call` per inner call through the existing `trackInnerCall`, attributed to the real tool as today.

---

## 3. Task runner and warm sandbox integration

_This section is in progress: the audit of the task sandboxes, notebook kernels and HogVM lands in the next commit._

---

## 4. Fast Mode: monetization and architecture

### 4.1 Standard Mode vs Fast Mode

|                              | Standard Mode (today, free)                                                                                       | Code Mode (free, capped)         | Fast Mode (paid)                                                                           |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------ |
| Model interaction            | `search` → `info` → `schema`\* → `call`, one turn each                                                            | `types` → `run`                  | same as Code Mode                                                                          |
| Where transformations happen | In the model's context                                                                                            | In a per-request isolate in Hono | In a warm pooled isolate in Hono                                                           |
| Isolate start                | n/a                                                                                                               | cold context per run             | pre-warmed, SDK pre-compiled, active project and scopes resolved before the run            |
| Budgets                      | 480 req/min burst, 4,800/h sustained (`DEFAULT_BURST_LIMIT`, `DEFAULT_SUSTAINED_LIMIT` in `hono/rate-limiter.ts`) | §2.3 standard column             | §2.3 Fast column, plus a separate inner-call rate bucket                                   |
| Inner-call parallelism       | none (one command per request)                                                                                    | 4                                | 16                                                                                         |
| Result budget to model       | whole API page                                                                                                    | 8k tokens                        | 32k tokens                                                                                 |
| Long-running work            | n/a                                                                                                               | 15 s wall                        | 60 s wall; longer jobs hand off to a Temporal-backed async run (§3) with a pollable handle |

### 4.2 Cost economics

Who pays for what depends on where the model runs:

- **Bring-your-own-model clients** (Claude Code, Cursor, Codex, Claude web/desktop). The user's vendor bills the model tokens. PostHog pays for Hono CPU, Django API calls and ClickHouse. Code Mode _reduces_ PostHog's load per task (fewer, better-aggregated calls) and cuts the user's token bill. Fast Mode's billable unit here is **sandbox compute plus inner calls**.
- **PostHog-hosted agents** (PostHog AI, PostHog Desktop/Code, Signals, scheduled tasks). PostHog pays model tokens and resells them as AI credits through the `$ai_generation` pipeline in `posthog/tasks/usage_report.py` (`_get_teams_with_ai_credits_for_products`, with a per-product markup). Here the token savings go straight to PostHog margin or to a lower customer price.

Input-token model for a task with T model turns, base context C₀ (system prompt, tool entry, conversation) and average per-turn growth r (the previous call and result):

```text
Standard:  input ≈ Σ_{k=1..T} (C₀ + k·r) = T·C₀ + r·T(T+1)/2      (quadratic in T)
Code Mode: input ≈ T'·C₀ + r'·T'(T'+1)/2 with T' ≈ 2–3, and r' ≈ size of ph.output()
Output:    Standard ≈ T·(≈150 tok per exec command)
           Code Mode ≈ script (≈400–1,200 tok) + final answer
```

Worked example: "find active flags with no evaluations in 30 days and archive them", 40 active flags, no prompt caching.

|                   | Standard                                                      | Code Mode                                      |
| ----------------- | ------------------------------------------------------------- | ---------------------------------------------- |
| Turns (T)         | search, info, list, 40× usage lookups, info, 12× updates ≈ 56 | types, run (dry run), run (writes) = 3         |
| C₀                | ≈ 12k (9k server + 3k conversation)                           | ≈ 13.5k (adds the `featureFlags` types)        |
| r                 | ≈ 1.2k                                                        | ≈ 1.5k (script + envelope)                     |
| Input tokens      | 56·12k + 1.2k·1,596 ≈ **2.6M**                                | 3·13.5k + 1.5k·6 ≈ **50k**                     |
| Output tokens     | ≈ 8k                                                          | ≈ 2.5k                                         |
| PostHog API calls | ≈ 56 sequential                                               | 1 SQL aggregation + 12 updates, 4-way parallel |

Prompt caching lowers the effective price of the standard input (most of each turn is a cached prefix), but not the turn count or wall time. Output tokens cost several times more per token than input on all current frontier models, so Code Mode's larger single output is still a small share of the total.
Use current list prices from the provider when you turn this into dollars. This doc deliberately quotes none.

When Code Mode does _not_ win:

- Single-call tasks: `types` + `run` costs more than one `call`.
- Tasks where the model must reason over every row (qualitative review of 30 session summaries). Code can't shrink that output without losing what the model needs.

The `run` guidance in §2.5 ("more than two calls, a loop, filtering, joins, or arithmetic") encodes this.

PostHog compute per run (to validate in PR 5 with `scripts/load-test.ts`): an isolate context with the SDK stubs should cost single-digit milliseconds from a warm pool, far less than one Django request. Cost is dominated by inner calls, and aggregation in `ph.query.sql` usually beats paging. So Fast Mode's marginal cost per task should be _lower_ than Standard's, and the price reflects value (speed, higher budgets), not cost recovery.

### 4.3 Opt-in, entitlement and model tiers

- **Opt-in.**
  - Code Mode (capped) rolls out behind feature flag `mcp-code-mode`, by team, using the existing flag plumbing in `request-state-resolver.ts`.
  - Fast Mode is an organization-level billing add-on. It is exposed to the catalog as a `feature_entitlement` (the YAML key already exists, 25 tools use it), and `getToolsForFeatures` reads it through `availableFeatures`.
  - Users can force a mode with `?mode=code` or the `x-posthog-mcp-mode` header, the same way `?mode=tools|cli` works today.
- **Model tier selection** applies only to PostHog-hosted agents, where PostHog picks the model:
  - Route all new callers through `PostHog/ai-gateway`, not `services/llm-gateway`, which is frozen.
  - Code generation against a typed SDK is where smaller, faster models do well. Default Fast Mode's hosted surfaces to the current fast tier (for example Claude Haiku 4.5), escalate on a failed `run` to the current mid tier (Claude Sonnet 5), and keep the top tier (Claude Opus 5.5) for planning-heavy tasks.
  - The brief names Claude 3.7 Sonnet and GPT-4o. Those are superseded, so choose from current models at implementation time and let evals (§5, PR 8) pick the defaults.
  - Bring-your-own-model clients choose their own model. PostHog does not pick one for them.
- **Rate limits.** The inner-call rate bucket is separate from the transport bucket, keyed by team (so one user's script cannot starve the team's other agents) and by user. Fast Mode raises both. The outbound 429 policy in `api/client.ts` (3 retries, 30 s total wait budget) stays. Inside a run, a 429 pauses only that call's promise, not the run.
- **Billing meters.**
  - New usage key `mcp_code_mode_compute`, in isolate CPU-milliseconds, rounded per run.
  - Optional second key `mcp_code_mode_inner_calls`.
  - Both are emitted as server-side events from Hono (with the `$mcp_*` properties the SDK already sets) and summed in `usage_report.py` the same way `ai_credits` is.
  - A generous free allowance keeps capped Code Mode effectively free. Fast Mode lifts the caps and bills above the allowance.
  - For hosted agents, tag generations with `ai_product = 'mcp_code_mode'` so the existing AI credit query covers them without a new pipeline.

---

## 5. Step-by-step implementation plan

Ordered by impact over engineering cost.
Each PR is independently shippable and flag-gated.
The evals harness (`services/mcp/evals`) is the go/no-go signal from PR 8 on.

|  PR | Title (conventional commit)                                           | What                                                                                                                                                                                                                                                                        | Impact                                                                 | Complexity |
| --: | --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ---------- |
|   1 | `fix(mcp): require --confirm for destructive tools reached via exec`  | Pass `requireDestructiveConfirmation: true` to the Hono `createExecTool` behind a flag. Measure the `needs_confirmation` rate                                                                                                                                               | Closes §1.6. Precondition for tier C                                   | S          |
|   2 | `feat(mcp): record exec turn chains per conversation`                 | Add `exec_chain_index` and `previous_verb` to `ExecCommandMeta`. Add an MCP analytics query for turns per task and N+1 detection (same tool called N times in a row)                                                                                                        | Baseline for every claim in §4.2                                       | S          |
|   3 | `feat(mcp): generate typed ph sdk declarations from tool definitions` | Extend `scripts/generate-tools.ts` to emit `posthog-sdk.d.ts` per domain, plus `code_mode` tier resolution. Add the `exec types` verb. No execution yet                                                                                                                     | Makes the SDK reviewable, and measures d.ts vs JSON Schema token sizes | M          |
|   4 | `feat(mcp): code_mode tier key in tools.yaml with lint`               | Add `code_mode` to `yaml-config-schema.ts` with an annotation-derived default. Lint: destructive ⇒ `deny`; billing, access control and credential categories ⇒ `deny`                                                                                                       | Makes safety declarative                                               | S          |
|   5 | `feat(mcp): isolate runtime for code mode`                            | Add the sandbox module under `services/mcp/src/code-mode/`: esbuild type-strip, isolate pool, host bindings that call the `exec call` inner dispatch (refactor that block of `exec.ts` into a reusable `dispatchInnerCall()` first), budgets, envelope. Unit and perf tests | Core capability                                                        | L          |
|   6 | `feat(mcp): exec run verb and execute_code tool`                      | Wire `run` (parsed before `splitBatchedCommands`), `?mode=code`, `code-mode.md` prompt section across the three command-reference variants, and fallback classification (§2.5 table)                                                                                        | Model-facing launch behind `mcp-code-mode`                             | M          |
|   7 | `feat(mcp): per-conversation code mode degradation state`             | Redis state machine, domain degradation, `tools/list_changed` re-render where supported                                                                                                                                                                                     | Graceful fallback                                                      | M          |
|   8 | `chore(mcp): multi-step code mode tasks in eval benchmark`            | Add benchmark v3 tasks built around F6 (N+1) shapes. Score Standard vs Code Mode on success, tokens per task, turns and p95                                                                                                                                                 | Go/no-go evidence                                                      | M          |
|   9 | `feat(mcp): posthog-cli api run for local code mode`                  | The same SDK and runtime in the local CLI (`src/cli`). Scripts run on the user's machine against their API key                                                                                                                                                              | Client-side path (§3) at almost no extra cost                          | S          |
|  10 | `feat(mcp): async code mode runs via temporal`                        | Runs over 60 s become a workflow with a result handle (`run --async`, `run-status <id>`), results stored by reference (the 2 MiB Temporal payload rule)                                                                                                                     | Long analyses                                                          | M          |
|  11 | `feat(billing): mcp code mode usage meters and fast mode entitlement` | Emit compute and inner-call usage, add them to `usage_report.py`, an org-level entitlement, and raised budgets when entitled                                                                                                                                                | Monetization                                                           | M          |
|  12 | `chore(mcp): document code mode`                                      | Update `services/mcp/README.md` / `CONTRIBUTING.md` and the generated `exec-command-reference.md`                                                                                                                                                                           | Adoption                                                               | S          |

Suggested sequencing: PRs 1–4 in parallel (weeks 1–2), PR 5 (weeks 2–4), PRs 6–8 (weeks 4–6, launch to internal teams), PRs 9–10 (weeks 6–8), PR 11 after eval results justify a paid tier.

Open questions to settle before PR 5:

1. Which isolate: V8 isolates (`isolated-vm`, native addon, fastest) or QuickJS compiled to WASM (pure JS dependency, stronger isolation, slower)? §3 has the evidence for each.
2. Should tier B writes in a run need a dry run first by default, or only past N writes?
3. Is `mcpConversationId` present on enough traffic to key degradation state, or should the key fall back to `mcpSessionId` + user hash?

---

## Appendix A: how the numbers were measured

- Catalog counts, categories and annotations: parsed from `services/mcp/schema/tool-definitions-all.json`.
- Per-tool entry sizes: `ToolCatalog.warmup()` then `getPreBuiltEntries()`, `JSON.stringify(entry).length / 4`, run in a throwaway vitest file (not committed).
- Instruction and command-reference sizes: `InstructionsFormatter.build*` with every tool in the catalog, `docsSearchEnabled: true`, empty guidelines. Real sessions see fewer tools (scopes and flags filter them), so these are upper bounds.
- Search latency: mean of 250 `searchToolsRanked` calls (5 queries × 50) and 50 `searchToolsRegex` calls over the 1,034-tool catalog, in the vitest process on the dev container.
- Not measured, and needed from production: turns per task, the distribution of `exec_verb` sequences, per-client error rates. See PR 2.
