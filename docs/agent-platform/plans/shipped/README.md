# Shipped plans

Design docs whose core design has fully landed as code. They live on here
(rather than being deleted) as the rationale-of-record for what shipped and
why. Each file's status header links to the implementation.

Only optional polish / future-work tails may remain open on these — anything
load-bearing that's still pending keeps a plan in the parent `plans/` folder
instead.

- [`session-restart-and-state-machine.md`](session-restart-and-state-machine.md)
  — the `queued → running → completed → closed` (+ `cancelled` / `failed`)
  state machine every trigger and resume path consumes.
- [`cron-trigger-scheduler.md`](cron-trigger-scheduler.md) — `cronTick()` in
  the janitor wakes `cron`-trigger agents; dedup via session `idempotency_key`.
- [`typed-bundle-authoring-api.md`](typed-bundle-authoring-api.md) — typed
  resource endpoints with server-derived `spec.skills[]` / `spec.tools[]` and
  an AST + esbuild shape check at upload.
- [`approvals-ui.md`](approvals-ui.md) — the agent-console approvals surface
  (fleet list, per-agent tab, detail drawer, count badges).
- [`container-builds.md`](container-builds.md) — Docker images + CI for the
  node services and the console.
