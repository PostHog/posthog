# Smaller sandboxes for data-only PostHog AI conversations

> **Source:** outstanding_items.md § 1 (Item 1) · **Locus:** backend — Temporal provisioning
> **Effort:** S–M (CPU / memory / disk sizing; M if a slim image variant is added later) · **Priority:** Highest (user-stated) · **Blocks rollout:** No (cost/latency lever)
> **Target small spec:** **1 CPU / 1 GB RAM / 10 GB disk** (fallback 2 CPU / 4 GB if 1 GB OOMs under load).
> **Joins:** Standalone backend pass. Cross-references G6 (`resources_used` bar) only — that is the per-turn product signal these same conversations emit, but it is frontend render work at a different locus and must NOT be merged here.

## Problem

Every sandbox the tasks runtime provisions is sized identically — **4 CPU / 16 GB RAM** — regardless of what it runs. PostHog AI (Max) conversations are pure data Q&A over MCP tools: they create a Task with `repository=None`, never clone a repo, never run a build, and never need the coding toolchain. They just talk to the agent server, which calls MCP tools (SQL execution, insight/dashboard/notebook creation) against PostHog's API.

Provisioning a coding-grade machine for a no-repo data conversation is wasted Modal spend on every turn and adds avoidable boot latency (more vCPU/memory to schedule and allocate). The intent is fully knowable at provision time (origin product + no repository), but nothing in the provisioning path reads it — the config is built with hardcoded defaults and never parameterized by intent.

## Current behavior (verified)

All line numbers below were re-opened and confirmed on 2026-06-13. Where the triage doc drifted, the corrected location is noted.

**SandboxConfig defaults** — `products/tasks/backend/services/sandbox.py:77-79` (doc said `:68-81`; the class starts at `:68`, the three sizing fields are `:77-79`):

```python
memory_gb: float = 16
cpu_cores: float = 4
disk_size_gb: float = 64
```

**Config is built with those defaults, never parameterized by intent** — `products/tasks/backend/temporal/process_task/activities/provision_sandbox.py:356-364` (confirmed exact). `create_sandbox_for_repository` constructs `SandboxConfig(...)` and passes `name`, `template`, `environment_variables`, `snapshot_id`, `snapshot_external_id`, `metadata`, `vm_runtime` — **no `cpu_cores` / `memory_gb` / `disk_size_gb`**, so every sandbox inherits the 4/16/64 defaults.

**Defaults map straight to Modal** — `products/tasks/backend/services/modal_sandbox.py:357-358` (confirmed exact), inside the `create_kwargs` dict at `:352-361`:

```python
"cpu": float(config.cpu_cores),
"memory": int(config.memory_gb * 1024),
```

**`disk_size_gb` is currently dead config — and must be wired for the disk part of the spec to take effect.** It is declared on `SandboxConfig` but **consumed by neither backend** — `modal_sandbox.py`'s `create_kwargs` (`:352-361`) passes only `cpu` and `memory` (no disk key), and `docker_sandbox.py` never reads it. So today both the existing "64 GB" and the new "10 GB" are nominal: Modal hands every sandbox a platform-managed ephemeral disk and we never request a specific size. To make the **10 GB** target real, this pass must add a disk / ephemeral-storage key to `create_kwargs` (step 4a) **iff** the installed Modal SDK exposes such a parameter on `Sandbox.create` — verify, because Modal sizes sandbox disk implicitly and may accept no explicit knob. If it does not, set `disk_size_gb=10` on the small `SandboxConfig` anyway (it documents intent and is honored by any backend that reads it, e.g. `docker_sandbox`), but treat the Modal disk as platform-managed and out of our control. **CPU and memory are the levers that always take effect.**

**PostHog AI is always no-repo** — `products/posthog_ai/backend/message_routing.py:351` (confirmed exact) in `_handle_first_message`, and also `:249` in `_prewarm_first`. Both call `Task.create_and_run(..., origin_product=Task.OriginProduct.POSTHOG_AI, repository=None, ...)`.

**Intent is knowable at provision time.** `TaskProcessingContext` (`get_task_processing_context.py:30-142`) already carries both `origin_product` (`:44`, set from `task.origin_product` at `:350`) and `repository` (`:42`, set from `task.repository` at `:348`). `TaskProcessingContext.mode` is at `get_task_processing_context.py:64-67` (doc said `:65-67` — the `@property` decorator is `:64`). The no-repo provisioning branch is `provision_sandbox.py:239-240` (confirmed exact: `elif not has_repo:` → "Creating environment without repository").

**`PostHogAIRunState`** — doc cited `message_routing.py:366-373`, but that range is only where the run-state **dict is assembled**. The actual class lives at `products/posthog_ai/backend/run_state.py:14-23` and subclasses `RunState` (`products/tasks/backend/temporal/process_task/utils.py:170-193`). `RunState` is `extra="allow"`, so it already tolerates new keys without a schema change. `TaskRun.state` is the persisted bag; the context's `state` dict (`get_task_processing_context.py:256`, `:355`) is what every activity reads.

**Feature-flag-in-context precedent.** `get_task_processing_context.py` already resolves two org-scoped flags into deterministic context booleans at workflow start, captured once so a mid-run flip can't introduce nondeterminism: `_is_modal_vm_sandbox_enabled` (`:184-220`) → `use_modal_vm_sandbox` (`:62`), and `_is_sandbox_event_ingest_enabled` (`:145-181`) → `sandbox_event_ingest_enabled` (`:61`). Both support a `state` override (read first) before consulting `posthoganalytics.feature_enabled`. The flag constants live in `products/tasks/backend/constants.py:3-4`. **This is the exact template for the rollout flag here.**

**Other no-repo origins exist — the derivation must not misfire.** A repo-wide audit of `repository=None` task creators shows PostHog AI is **not** the only no-repo origin:

- `products/signals/backend/report_generation/select_repo.py:69,83` and `products/signals/backend/custom_agent/base.py:389,617` resolve `SIGNAL_REPORT` / `SIGNALS_SCOUT` repo selection to `repository=None` when no candidate repo is found (`:83`/`:389` are the `RepoSelectionResult(repository=None, ...)` "no plausible candidate" path; `:69`/`:617` are the `origin_product=...SIGNAL_REPORT` context). Those `None` repositories then flow into real compute tasks.
- `posthog/temporal/ai/posthog_code_slack_mention.py` resolves a `SLACK` origin to no repo (`PostHogCodeRepoCascadeOutcome(... repository=None ...)` at `:596,:614,:615,:624`; the `SlackRepoSelectionOutcome(repository=None, ...)` failure/no-match builders at `:691,:705,:718,:727` carry the selection result, not the task). The actual `SLACK`-origin task is created by `create_posthog_code_task_for_repo_activity` (`:938`) via `Task.create_and_run(..., origin_product=Task.OriginProduct.SLACK, repository=repository, ...)` at `:999-1005`, where `repository` is the pass-through value and can be `None`.

A Signals scout or Slack-mention task running with no repo is a real coding/exploration agent that may genuinely need compute. **Therefore "no repo ⇒ small" is wrong; the gate must be `origin_product == POSTHOG_AI` AND `repository is None`.** PostHog AI is the only origin that is _always and only_ no-repo data Q&A.

## Approach

**Chosen design: implicit derivation from `(origin_product, repository)`, gated by a rollout flag, sized to 1 CPU / 1 GB RAM / 10 GB disk — no new wire field, no slim image yet.**

1. **Derivation, not a new signal.** Because PostHog AI is the only origin that is _always_ no-repo data Q&A, add no `sandbox_tier` field to `run_state` / `ProcessTaskInput`. Derive the tier inside provisioning from data already on the context: `ctx.origin_product == Task.OriginProduct.POSTHOG_AI and ctx.repository is None`. (`ctx.origin_product` is typed `str | None` at `get_task_processing_context.py:44` and holds the stored string value; the comparison works because `Task.OriginProduct` is a `TextChoices`, so `Task.OriginProduct.POSTHOG_AI == "posthog_ai"`. Compare against the enum member, not a bare literal, so a value rename stays caught.) Add a single helper `is_data_only_sandbox(ctx) -> bool` (in `provision_sandbox.py` or `get_task_processing_context.py` as a `TaskProcessingContext` property) so the rule has one home and is unit-testable.

   _Rejected alternative — explicit `sandbox_tier` carried through `run_state`/`ProcessTaskInput`:_ more plumbing (new `PostHogAIRunState`/`RunState` key, set it in two `message_routing.py` call sites and both prewarm paths, thread it through the activity), and it buys nothing today because the only consumer is PostHog AI and the derivation is unambiguous. The right time to introduce an explicit tier is if/when a *non-*PostHog-AI flow wants a small box or a PostHog AI flow wants to opt **up** (see escape hatch). Until then, an explicit field is speculative generality. We keep the door open by routing the decision through the single helper, so swapping the implicit rule for an explicit field later touches one function.

2. **Size CPU, memory, and disk.** The small spec is **1 CPU / 1 GB RAM / 10 GB disk**. Compute all three from the helper and pass them into the `SandboxConfig(...)` build at `provision_sandbox.py:356-364`. CPU and memory take effect immediately via Modal's `create_kwargs`; `disk_size_gb` only takes effect once it is wired into `create_kwargs` (step 4a) and only if Modal exposes a disk knob — see the disk caveat under Current behavior. (The agent server is a Node/Python process doing HTTP + MCP calls and streaming SSE; it is I/O-bound on the model and PostHog API, not CPU-bound. Query results stream back as JSON bounded by API paging, not held in a large in-memory set.) **1 GB is the aggressive part of the spec** — validate empirically before widening, and fall back to **2 CPU / 4 GB** if turns OOM/throttle under load (see Testing).

3. **CPU/mem cut first, slim image deferred.** Do _not_ build a new slim image variant in this pass. The existing `SandboxTemplate.DEFAULT_BASE` image already boots and runs the agent server for PostHog AI today; the toolchain it carries is unused weight on disk but does not cost CPU/RAM at runtime, and image pulls are cached/snapshot-backed. A separate slim image means a new `SandboxTemplate`, a new Modal app/image build, a new Dockerfile, and its own cache-warming — strictly more to ship and operate for a marginal boot win on top of the CPU/mem win. Ship the CPU/mem cut, measure boot time, and only then decide whether a slim image is worth a follow-up.

4. **Gate behind a rollout flag, mirroring the existing pattern.** Add `SMALL_DATA_SANDBOX_FEATURE_FLAG = "tasks-small-data-sandbox"` to `products/tasks/backend/constants.py`. Resolve it in `get_task_processing_context.py` exactly like `use_modal_vm_sandbox`: a `_is_small_data_sandbox_enabled(...)` helper (state override → org-scoped `posthoganalytics.feature_enabled`), captured once into a new `small_data_sandbox_enabled: bool = False` context field. Provisioning shrinks the box only when `is_data_only_sandbox(ctx) and ctx.small_data_sandbox_enabled`. Capturing at workflow start keeps the decision deterministic for the whole run (the file's existing rationale, `:56-58`).

5. **Add telemetry.** Emit a counter tagging each provision with `tier` (`small` / `default`) and `origin_product`, and reuse the existing `StepTimer("sandbox_creation", ...)` (already wrapping `Sandbox.create` at `provision_sandbox.py:366`) so the `tasks_process_sandbox_step_latency` histogram lets us compare boot latency small-vs-default. The `StepTimer` class (`temporal/metrics.py:70-105`) today takes only `step` + `used_snapshot` and hardcodes its label set at `:90-94` — so adding `tier`/`origin_product` means extending the `__init__` signature and the `attributes` dict, not just passing kwargs at the call site. Keep the new labels low-cardinality (`tier ∈ {small, default}`, `origin_product` is a bounded enum) so the histogram series count stays bounded.

**Escape hatch for a rare heavy flow.** Two layers: (a) the `state` override that the flag helper reads first — a specific run can force `small_data_sandbox_enabled=False` via `run_state` to opt back up to the default box without touching the flag; (b) because the size lands through the single `is_data_only_sandbox`/size-computing helper, a future "this PostHog AI turn needs big" signal (e.g. a `force_full_sandbox` run-state key) is a one-function change. For v1, no PostHog AI flow is known to need heavy compute (no repo, no build, results stream paged) — so the escape hatch is the flag/state override, not new product code.

## Implementation steps

1. **Add the helper + tier rule.** In `provision_sandbox.py` (or as a `TaskProcessingContext` property in `get_task_processing_context.py`), add `is_data_only_sandbox(ctx) -> bool` returning `ctx.origin_product == Task.OriginProduct.POSTHOG_AI and ctx.repository is None`. Add the small-spec constants `SMALL_DATA_SANDBOX_CPU_CORES = 1.0`, `SMALL_DATA_SANDBOX_MEMORY_GB = 1.0`, `SMALL_DATA_SANDBOX_DISK_GB = 10.0`.
2. **Add the rollout flag constant** `SMALL_DATA_SANDBOX_FEATURE_FLAG = "tasks-small-data-sandbox"` to `products/tasks/backend/constants.py:3-4`.
3. **Resolve the flag into the context.** Add `_is_small_data_sandbox_enabled(...)` to `get_task_processing_context.py` (copy `_is_modal_vm_sandbox_enabled` at `:184-220` verbatim, swap the flag constant and log keys), add `small_data_sandbox_enabled: bool = False` to `TaskProcessingContext` (next to `:62`), call the helper in `get_task_processing_context` (next to the `use_modal_vm_sandbox` call at `:323-333`), and pass it into the returned `TaskProcessingContext(...)` (`:340-364`).
4. **Apply the size in the config build.** At `provision_sandbox.py:356-364`, compute `cpu_cores`/`memory_gb`/`disk_size_gb` (default to the `SandboxConfig` defaults; override to the small constants when `is_data_only_sandbox(ctx) and ctx.small_data_sandbox_enabled`) and pass them into `SandboxConfig(...)`. Emit one `emit_agent_log(ctx.run_id, "debug", ...)` line stating the chosen tier for in-run visibility.
   4a. **Wire disk into Modal.** In `modal_sandbox.py`'s `create_kwargs` (`:352-361`), add a disk / ephemeral-storage key sourced from `config.disk_size_gb` **iff** the installed Modal SDK exposes such a parameter on `Sandbox.create` — verify against the SDK, since Modal currently sizes sandbox disk implicitly. If no such parameter exists, leave `create_kwargs` unchanged and call out in the PR that `disk_size_gb` is documentation-only on the Modal backend; CPU + memory still deliver the bulk of the savings.
5. **Add telemetry.** Add `tier` + `origin_product` attributes to the `StepTimer("sandbox_creation", ...)` at `:366`, and add a small counter (mirror `increment_snapshot_usage` in `temporal/metrics.py:45-50`) `increment_sandbox_tier(tier, origin_product)`.
6. **Validate the spec** (see Testing) on internal teams behind the flag before widening.

## Files to change

| Path                                                                                     | Change                                                                                                                                                                                      |
| ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `products/tasks/backend/constants.py`                                                    | Add `SMALL_DATA_SANDBOX_FEATURE_FLAG`; (optional) the small CPU/mem constants if not colocated in provisioning                                                                              |
| `products/tasks/backend/temporal/process_task/activities/get_task_processing_context.py` | Add `small_data_sandbox_enabled` field (`~:62`), `_is_small_data_sandbox_enabled` helper (mirror `:184-220`), call + pass-through (`:323-333`, `:340-364`)                                  |
| `products/tasks/backend/temporal/process_task/activities/provision_sandbox.py`           | `is_data_only_sandbox` helper; compute `cpu_cores`/`memory_gb`/`disk_size_gb` and pass into `SandboxConfig(...)` at `:356-364`; tier debug log; tier attrs on the `StepTimer` at `:366`     |
| `products/tasks/backend/services/modal_sandbox.py`                                       | Wire `config.disk_size_gb` into `create_kwargs` (`:352-361`) **if** the Modal SDK exposes a disk parameter on `Sandbox.create`; otherwise no change (Modal manages sandbox disk implicitly) |
| `products/tasks/backend/temporal/metrics.py`                                             | Add `increment_sandbox_tier(tier, origin_product)` (mirror `increment_snapshot_usage`, `:45-50`); add `tier`/`origin_product` to `StepTimer` labels                                         |

No frontend, serializer, viewset, migration, or wire-type change. `RunState`'s `extra="allow"` means even the (rejected) explicit-field path would need no schema migration.

## Decisions & open questions

- **Implicit derivation vs explicit `sandbox_tier` field.** _Recommendation: implicit derivation_ (`origin_product == POSTHOG_AI and repository is None`). PostHog AI is the only always-no-repo data origin; an explicit field is speculative until a second consumer or an opt-up case exists. Keep the rule in one helper so a later switch is a one-function change.
- **Small spec: 1 CPU / 1 GB / 10 GB disk (fallback 2 CPU / 4 GB).** _Recommendation: start at 1 CPU / 1 GB / 10 GB disk behind the flag, validate, fall back to 2 CPU / 4 GB only if boots/turns regress._ The agent server is I/O-bound on the model + PostHog API and streams results paged, so 1 GB should fit — but it is aggressive; watch for OOM. Disk only becomes a real Modal request once `disk_size_gb` is wired into `create_kwargs` (step 4a) **and** only if Modal exposes a disk knob — otherwise 10 GB is the documented `SandboxConfig` value and Modal manages disk itself.
- **Slim image variant now vs CPU/mem only.** _Recommendation: CPU/mem only this pass._ A slim image is a new `SandboxTemplate` + Modal app/image build + cache warming for a marginal boot gain on top of the runtime-size win. Revisit as a follow-up only if boot telemetry shows image pull dominates.
- **Escape hatch for a heavy PostHog AI flow.** _Recommendation: rely on the flag's `state` override (force `small_data_sandbox_enabled=False`) for v1._ No known heavy PostHog AI flow exists (no repo/build, paged results). If one appears, add a `force_full_sandbox` run-state key read by the same helper.
- **Does the derivation misfire on other no-repo origins?** _Resolved: no, because we AND on `POSTHOG_AI`._ Verified that `SIGNAL_REPORT`, `SIGNALS_SCOUT`, and `SLACK` can also produce `repository=None`; those must keep the default box, which the origin-product gate guarantees.

## Dependencies & sequencing

- **Self-contained backend pass.** No dependency on other G-items to ship.
- **Cross-reference G6 (`resources_used` bar), do not merge.** G6 renders the per-turn "PostHog resources used" bar from `_posthog/resources_used` (typed at `frontend/src/scenes/max/types/sandboxWireTypes.ts:288` — corrected path; the triage doc's `frontend/src/scenes/max/sandboxWireTypes.ts` is stale and does not exist) and is frontend render work in `sandboxStreamLogic` + a bar component. It shares only the _subject_ (data-only PostHog AI conversations), not the _code locus_ (frontend SSE/render vs backend Temporal provisioning). Implement independently.
- Internal sequencing: steps 1–5 land together (one PR); step 6 (spec validation) gates widening the flag, not merge.

## Testing

- **Unit (Python, `parameterized`):** `is_data_only_sandbox` truth table over the cartesian product of `origin_product ∈ {POSTHOG_AI, SIGNAL_REPORT, SIGNALS_SCOUT, SLACK, USER_CREATED}` × `repository ∈ {None, "posthog/posthog"}` — only `(POSTHOG_AI, None)` is true. This is the regression guard against the misfire.
- **Unit:** `_is_small_data_sandbox_enabled` — state-override-true, state-override-false, flag-on, flag-off, flag-check-raises → False (mirror the existing `_is_modal_vm_sandbox_enabled` tests).
- **Unit:** the config-build path in `create_sandbox_for_repository` — assert `SandboxConfig.cpu_cores`/`memory_gb`/`disk_size_gb` are the small spec (1 / 1 / 10) when `(data-only AND flag on)`, and the 4/16/64 defaults otherwise (data-only + flag off; non-PostHog-AI no-repo; PostHog-AI-but-flag-off). Patch `Sandbox.create` to capture the config. If disk is wired (step 4a), also assert the disk key reaches `create_kwargs`.
- **Empirical validation (the real test):** behind the flag on internal teams, run representative PostHog AI conversations (a WAU trend question, a multi-insight dashboard build, a notebook-rendering turn) and confirm no OOM/throttle and acceptable turn latency on 1 CPU / 1 GB before widening (1 GB is the aggressive part of the spec — watch memory headroom closely). Watch the new `tier` telemetry + the `tasks_process_sandbox_step_latency` histogram for `sandbox_creation` small-vs-default.
- No jest/playwright (no frontend change).

## Rollout / flagging

- **Flag:** `tasks-small-data-sandbox`, org-scoped, resolved once at workflow start into `TaskProcessingContext.small_data_sandbox_enabled` (deterministic for the run; same pattern as `tasks-modal-vm-sandbox`). Default off → zero behavior change until enabled. `state`-override-first means a specific run can force the default box.
- **Gradual rollout:** internal org → validate spec → small % of PostHog-AI-enabled orgs → 100%. Because the gate ANDs on `origin_product == POSTHOG_AI`, flipping the flag broadly cannot accidentally shrink coding (`USER_CREATED`/`SLACK`/Signals) sandboxes.
- **Telemetry to confirm the smaller machine holds:** (1) `increment_sandbox_tier(tier, origin_product)` counter — volume of small vs default; (2) `tasks_process_sandbox_step_latency{step=sandbox_creation, tier}` — boot-latency delta; (3) existing run-failure/error rates split by tier (watch for OOM/throttle as small-tier-only failures); (4) Modal cost dashboards (small boxes should show lower per-run cost). If small-tier failure rate exceeds default, bump the spec to 2/4 or flip the flag off — both are config-only, no redeploy of agent code.

## Effort & risk

- **Effort:** S–M. The CPU / memory / disk sizing is a handful of edits across four–five files (the fifth, `modal_sandbox.py`, only if disk is wired) following an in-repo template (`tasks-modal-vm-sandbox`). It bumps toward M only if step 6 forces a slim-image follow-up — out of scope here.
- **Risks:**
  - _Under-provisioning._ 1 CPU / 1 GB is aggressive and may starve a heavy turn (large result post-processing, notebook artifact rendering) → OOM/throttle, more likely at 1 GB than the originally-scoped 2 GB. Mitigation: validate empirically before widening; tier telemetry surfaces it; 2 CPU / 4 GB fallback and flag-off are config-only.
  - _Misfire onto a non-PostHog-AI no-repo flow._ Fully mitigated by ANDing on `POSTHOG_AI` and locked by the parameterized truth-table test.
  - _Disk wiring._ `disk_size_gb=10` only takes effect if Modal exposes a disk parameter and step 4a wires it in; verify before claiming the disk is actually capped at 10 GB. If Modal manages disk implicitly, the 10 GB value is documentation-only on the Modal backend and the real disk stays platform-default. Query-result caching is bounded by API paging, so disk is not expected to be the runtime constraint either way.
  - _Determinism._ Resolving the flag inside `get_task_processing_context` (not inside provisioning) keeps the size decision stable across activity retries, matching the file's existing flag-capture rationale.
