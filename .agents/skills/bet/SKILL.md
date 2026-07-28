---
name: bet
description: Run the full Foundry bet lifecycle (create, fund, status, verdict, portfolio) from conversation, against the live PostHog REST API and a bet's git-backed memory repo. Use when the user says "/bet", asks to start/create a bet, wants a status update or "scout report" on a bet, wants to record a bet's verdict (promoted/rolled_back/iterate), or wants to see the bet portfolio. Never requires the user's session cookie — everything goes through a scoped personal API key.
---

# /bet — the Foundry front door

Foundry (`products/foundry/`) turns a hypothesis into an accountable, budgeted
unit of work: a **Bet** with one success metric, guardrails, and an
append-only event log that drives its state machine
(`drafted → funded → building → gated → exposed → verdict → archived`). This
skill is the developer interface to that lifecycle — a human runs the whole
loop in conversation and never has to read Foundry's code. See
`products/foundry/README.md` and the ADRs it links for the product design;
this skill only concerns itself with _using_ the API that product exposes.

Every step below is a small script in `scripts/`, so the whole flow is also
runnable non-interactively (that's how this skill was tested) — reuse the
scripts directly if you're scripting a bet rather than conversing about one.

## One-time setup

Read [references/setup.md](references/setup.md) and confirm
`~/.config/foundry/bet.env` exists before doing anything else. If it's
missing, walk the user through `scripts/mint-api-key.sh` — don't try to guess
or fabricate a key. `~/.config/foundry/memory.env` is optional; if it's
missing, memory steps are skipped with a clear note (never an error) —
tell the user this plainly rather than silently doing nothing.

Every script fails loudly with an actionable message (which env var, how to
get it) — surface that message to the user verbatim rather than retrying
blindly.

## `/bet` — start a new bet

**a. Interview the user to a crisp spec.** Push back on vague hypotheses —
this replaces the review a PR used to get, so it's the one place bet hygiene
still gets enforced by a human (you). Get:

- A **falsifiable hypothesis** ("X will increase Y" — not "improve onboarding").
- A **slug** (kebab-case, becomes the feature flag key `bet-<slug>`).
- **Exactly one** success metric (name + target) — the formal definition lives
  in the experiment `fund` creates; this is the one number that decides the bet.
- **Guardrails** — what must not regress.
- **Budget** (`usd`/`time_hours`/`iterations`), all optional but worth asking.
- **Sources** — what signal/report motivated this bet (label + URL).
- **`execution_mode`**: `external` (default — the user's own orchestrator
  posts events; you only print it the contract) or `managed` (Foundry runs a
  Temporal workflow itself). For `managed`, also get `run_config`
  (`{command, env, caps: {max_depth, max_children, max_cost}}` — `command` is
  a shell command, not agent reasoning; see
  [references/managed-run-config.md](references/managed-run-config.md) for
  the recursive-spawn protocol) and, if they want memory, which repo.
- Optional **rollout KPIs** — see step (c). Ask, but don't push: most bets
  are simple and skip this.
- **The gauntlet** (`gate_config`) — the constraint battery a builder can't
  weaken, since it's authored here, before the build, not by the agent doing
  the building. Recommend a default battery and let the user adjust it:
  - `tests` (`command`, required): the artifact's own test suite.
  - `typecheck` (`command`, required): a type-check command, if the language
    has one.
  - `coverage` (required, `min_changed_line_pct: 80`): changed-line coverage
    of the diff, not overall repo coverage.
  - `protected_paths` (the top-level field, not a check): non-empty whenever
    the bet uses the test-writer → builder pattern (see below) — this is the
    structural guarantee that the builder can't edit its own acceptance
    tests to make them pass.
  - Offer `mutation` (required=false unless the bet is genuinely high-stakes,
    e.g. billing, auth, data integrity) — it's expensive (time-boxed,
    `max_minutes`) and a copy-text bet doesn't need it; a payments bet does.
  - `reviewhog` is available as a check type too, but isn't part of the
    default battery — only add it if the user specifically wants an
    automatic ReviewHog pass as part of the gauntlet.
    Full check-type reference (params, defaults, the `command`/`coverage`/
    `mutation`/`flag_guard`/`reviewhog` shapes): read
    `products/foundry/backend/presentation/serializers.py`
    (`GateCheckSerializer` and the per-type params serializers) — it's the
    ground truth, don't guess at param names. For a `managed` bet using the
    test-writer → builder pattern, see
    [references/managed-run-config.md](references/managed-run-config.md)
    ("Triggering the gauntlet") for the `run_config` convention that produces
    an `artifact_ready` event the gauntlet can actually check out and diff.
    A bet with an empty `gate_config` (the default) never gets an automatic
    gauntlet run — it stays on the pre-ADR-4 manual `gate.result` path, which
    is still fine for a low-stakes or exploratory bet.

Write the spec to a JSON file matching `CreateBetSerializer`
(`products/foundry/backend/presentation/serializers.py` is the ground truth
for exact field names) and run:

```sh
scripts/create-bet.sh /path/to/spec.json
scripts/fund-bet.sh <slug>          # creates bet-<slug> flag + a draft experiment
```

Funding is what starts the Temporal workflow for a `managed` bet — nothing
further to do there. Surface the returned `feature_flag_key` and
`experiment_id` (build the links yourself: `<POSTHOG_URL>/project/<id>/feature_flags/<id>`
and `.../experiments/<id>`).

**b. Optional rollout KPIs.** If the user named metrics beyond the single
success metric (retention, active users, revenue...), build a small JSON file:

```json
[
  { "name": "...", "kind": "trends", "event": "$pageview" },
  { "name": "...", "kind": "retention" }
]
```

and run `scripts/kpi-dashboard.sh <slug> kpis.json` **after** funding (it
needs the bet's flag key to exist so insights can filter to it). This creates
a `Bet: <slug>` dashboard, one insight per KPI, and links it on the bet
timeline via a `note` event. Skip this step entirely for simple one-metric
bets — don't create ceremony nobody asked for.

**c. Memory.** For a `managed` bet that wants its memory repo cloned into
node sandboxes, get the URL _before_ `create-bet.sh` (there's no way to patch
`memory_repo_url` in after the fact) — decide which product the bet belongs
to and run `scripts/print-memory-url.sh <product>` (defaults to `foundry`),
and put its output straight into the spec's `memory_repo_url` field.

After the bet exists (any execution mode), seed the memory branch itself:

```sh
scripts/memory-seed.sh <slug> /path/to/spec.json [--dashboard-url URL]
```

This creates/pushes `bet/<slug>` in the product's memory repo (see
[references/memory-conventions.md](references/memory-conventions.md) for the
convention this follows).

**d. Build kickoff.** For `external` bets, run
`scripts/print-contract.sh <slug>` and hand the user the printed contract —
that's the entire interface their orchestrator needs. For `managed` bets,
nothing further; funding already started the run.

## `/bet status <slug>` — the scout report

Run `scripts/status.sh <slug>` and relay its output. It renders: state,
hypothesis, guardrails, the node tree (indented by depth), the gate outcome —
pass/fail/skipped, and if the gauntlet ran, a per-check breakdown (name,
type, required/optional, pass/fail, details — this is the "gate card" the UI
also shows) — any `knowledge.published` entries, the KPI dashboard link if
one exists, and the linked feature flag/experiment (with a best-effort fetch
of experiment start/end dates). This has to be legible to someone who has
read none of the code — don't just dump JSON, narrate what the script
printed, and call out a failing _required_ check distinctly from a failing
optional one.

## `/bet verdict <slug>` — decide and record

1. Run `scripts/status.sh <slug>` to gather the same evidence a human would
   read.
2. **You** recommend `promoted` / `rolled_back` / `iterate` with reasoning
   grounded in that evidence (metric movement vs. target, guardrail status,
   gate result, exposure duration) — this is a judgment call, not something a
   script decides. Push back if the evidence is too thin for a real verdict
   (e.g. no exposure time yet) rather than rubber-stamping a promote.
3. On the user's decision, run:

   ```sh
   scripts/record-verdict.sh <slug> <promoted|rolled_back|iterate> "<one-line reasoning>"
   ```

   This records the verdict via the API, then runs the real memory
   choreography (updates the bet's memory entry with the verdict _first_,
   then `promoted` → merges `bet/<slug>` into `main`; `rolled_back` → tags
   `archive/<slug>` and extracts the learning entry onto `main`; `iterate` →
   branch stays for the next round). It degrades gracefully if memory.env
   isn't configured.

## `/bet list` — the portfolio

Run `scripts/list-bets.sh` and relay it as-is — one line per bet (slug,
state, mode, iteration, metric).

## Design notes

- Every script sources `scripts/lib.sh`, which loads the env files, wraps
  `curl`+`jq` in `api_call`/`api_call_ok`, and resolves a bet by slug or UUID
  (`resolve_bet_id`) — there's no get-by-slug route, only list-and-filter.
- All scripts are idempotent where it matters (memory clone/fetch/reset) and
  safe to re-run.
- `record-verdict.sh` calls `memory-verdict.sh` internally — call the latter
  directly only if you've already recorded the API-side verdict some other
  way and just need to re-run the git choreography.
