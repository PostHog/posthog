# PostHog AI migration — outstanding-item implementation plans

Implementation-ready plans for every item in [`../outstanding_items.md`](../outstanding_items.md) (the 6 newly-noticed items in §1–6 plus the §8 gaps that needed planning).
Each plan stands alone — it restates the problem from the code, carries verified `file:line` references, lists files to change, surfaces the decisions a human must make, and sizes the work.

Every plan was drafted against the code and then adversarially verified: a second pass re-opened every cited file, corrected drifted line numbers in place, and fixed unsound claims. Each plan landed at **high** confidence. Where the verifier changed a plan's conclusion, it's called out below.

## How the 15 source items were joined into 9 passes

Tasks were merged only when they share a code locus (one cohesive PR), not merely a theme.

| Plan                                                                                  | Folds in (from `outstanding_items.md`)                                                                        | Locus                                      |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| [G1 — small data-only sandboxes](./G1-small-data-sandboxes.md)                        | § 1                                                                                                           | backend — Temporal provisioning            |
| [G2 — cancel "bail" button](./G2-cancel-bail-button.md)                               | § 2                                                                                                           | frontend — Max composer                    |
| [G3 — conversation serializer query cost](./G3-conversation-serializer-query-cost.md) | § 3                                                                                                           | backend — serializer + models              |
| [G4 — legacy history → sandbox conversion](./G4-legacy-history-conversion.md)         | § 4                                                                                                           | decision gate + (conditional) converter    |
| [G5 — sandbox tool-card parity](./G5-sandbox-tool-card-parity.md)                     | § 5 / §8 diffs **+** §8 `_meta.claudeCode.*` **+** §8 built-in tool mapping                                   | frontend — tool-call cards                 |
| [G6 — sandbox notification rendering](./G6-sandbox-notification-rendering.md)         | §8 `resources_used` bar **+** §8 `usage_update`/`status`/`compact_boundary`/`task_notification`/`sdk_session` | frontend — notification dispatch           |
| [G7 — sandbox streaming resilience](./G7-sandbox-streaming-resilience.md)             | §8 pre-first-message statuses **+** §8 crash telemetry/affordance **+** §8 richer SSE reconnect               | frontend — stream lifecycle                |
| [G8 — `refresh_session` relay allowlist](./G8-refresh-session-relay-allowlist.md)     | §8 `refresh_session`                                                                                          | backend — relay serializer + sandbox proxy |
| [G9 — Max mobile friendliness](./G9-max-mobile-friendliness.md)                       | § 6                                                                                                           | frontend — responsive layout               |

`_posthog/progress` (mentioned in §8) is deliberately **not** a plan — PostHog already consumes it (`sandboxStreamLogic.ts:882-886`); there is nothing to build.

## Sequenced roadmap

| Order | Plan                              | Effort                                      | Priority                        | Blocks rollout      |
| ----- | --------------------------------- | ------------------------------------------- | ------------------------------- | ------------------- |
| 1     | G2 cancel button                  | S (S–M w/ sandbox teardown)                 | High                            | No                  |
| 1     | G3 serializer query cost          | S                                           | Medium-high                     | No                  |
| 2     | G1 small data-only sandboxes      | S–M                                         | **Highest** (user-stated)       | No                  |
| 3     | G4 legacy history (decision gate) | ~0 (Option A) / L (Option B)                | Medium-high\*                   | Depends on decision |
| 4     | G5 tool-card parity               | M (A+B core; C deferred)                    | Medium-high                     | No                  |
| 4     | G8 `refresh_session`              | S–M                                         | Medium (blocks MCP hot-loading) | No                  |
| 5     | G6 notification rendering         | M (incremental; `resources_used` first = S) | Medium                          | No                  |
| 5     | G7 streaming resilience           | M                                           | Low-medium                      | No                  |
| 6     | G9 mobile friendliness            | M                                           | Lowest (user-stated)            | No                  |

\* G4's effort/priority collapse to ~0 if runtime **coexistence** is accepted — make that call first.

1. **Quick wins first** — G2 and G3 are both S and independent. Clear them early. (G2 turned out S–M once the sandbox teardown bug it uncovered is folded in; see below.)
2. **Biggest lever** — G1. Highest user-stated priority; the plumbing template already exists, so it's S–M, not M.
3. **Decision gate** — G4. The recommendation is **Option A (coexistence)**, which is ~0 work because it _is_ the current behavior. Only schedule the L converter if there's a hard deadline to retire the LangGraph runtime _and_ reopenable history is required.
4. **Parity / correctness** — G5 (fixes silent denial-data loss + built-in tool names) and G8 (unblocks MCP hot-loading).
5. **Render polish** — G6 (`resources_used` bar first) and G7 (crash affordance + provisioning status). These two share a stream-status surface — see coordination note.
6. **Deferred** — G9 (lowest), and the G5 code-diff sub-task (no producer exists yet).

## Findings that changed the plan (read before scheduling)

- **G1 — target spec 1 CPU / 1 GB / 10 GB disk; two doc assumptions were wrong.** `disk_size_gb` is currently **dead config** (neither Modal nor Docker backend reads it — even "64 GB" is never requested), so the 10 GB disk only takes effect if it's wired into Modal's `create_kwargs` _and_ Modal exposes a disk knob (verify — Modal sizes sandbox disk implicitly); CPU + memory are the levers that always apply, and 1 GB is the aggressive part of the spec (2 CPU / 4 GB fallback). And **"no repo ⇒ small" would misfire**: Signals and Slack also create legitimate no-repo _compute_ agents. The gate must be `origin_product == POSTHOG_AI` **AND** `repository is None`. Recommend an implicit derivation (no new field), behind a `tasks-small-data-sandbox` flag mirroring the existing `_is_modal_vm_sandbox_enabled` template.
- **G2 — uncovered a worse, always-on bug.** Beyond the reported post-cancel race (LangGraph path), the sandbox path **never** dispatches `completeThreadGeneration`, so `streamingActive` stays stuck after _every_ turn. There is no separate frontend sandbox cancel relay (the doc's premise) — both runtimes cancel through one backend endpoint. Fix needs a narrow `endStreaming` action (reusing `completeThreadGeneration` for error paths would wrongly auto-drain the queued-message buffer).
- **G3 — there IS a prefetch-dependent caller** of `Task.latest_run` (the tasks list endpoint), so use a **prefetch-aware property**, not a bare `.first()`. The frontend needs zero type changes — the `task.current_run_id` shape already exists; the fix is a list-queryset subquery annotation.
- **G4 — the doc's framing is wrong.** Legacy history is **PostHog schema messages** (typed tool calls), not raw LangChain objects, so a converter is more tractable than stated — but coexistence is still the recommendation.
- **G5 — confirmed silent data loss.** Built-in tool cards can't match the registry until `_meta.claudeCode.toolName` is read (Twig sends no top-level `toolName` for built-ins), and denial reasons are dropped. The type must be rewritten flat→nested. **No diff producer exists in PHAI today**, so the code-diff sub-task is deferred-until-producer; A+B ship without it.
- **G6 — `usage_update` has a wire-shape mismatch** that silently drops Claude usage (the typed union only models the Codex two-frame split). Reconcile the type before building the usage UI. `resources_used` (the bar) ships first as an S.
- **G7 — an agent crash is currently invisible**, not "a generic error" — the crash message is captured to telemetry but no thread item is rendered, and an exhausted reconnect budget unlocks the composer silently. Provisioning progress is already _received_ and stored but gated off by `isThinking`; the fix is a render gate, not new server data.
- **G8 — security crux flips the design.** The documented approach (browser POSTs the full `mcpServers` array with bearer tokens to `/command/`) is a credential-injection/SSRF risk because the relay forwards params verbatim. The plan recommends a **server-side `refresh_mcp` conversation action** (no client-supplied servers) instead — an intentional deviation from `04_PROMPTS.md § 5.4` that the spec docs will need to reflect.
- **G9 — the `useBreakpoint` hook referenced by the doc/brief does not exist.** The repo's primitive is `useWindowSize`; `SidePanel.tsx` already uses it and already treats `< lg` as mobile, so the fix extends existing machinery. Standardize on `md`/`lg` (the `sm` breakpoint disagrees between the CSS and JS sources — 576 vs 526).

## Cross-plan coordination

- **G6 + G7** both introduce a stream-status line above/within the thread. Whichever lands first should own a shared `StreamStatusLine`; the other consumes it.
- **G1 + G6 (`resources_used`) + G7 (provisioning status)** all shape the data-only-conversation experience — sequence them aware of each other.
- **G4 visualization/notebook fidelity** depends on G5's extractors; don't duplicate that work in the converter.
