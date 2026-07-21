---
name: extending-personhog-test-harness
description: >
  When and how to add scenarios, chaos events, and invariants to the personhog
  e2e test harness (rust/personhog-test-harness). Use after fixing a bug or
  regression in the personhog leader path (leader, router, writer, replica,
  coordination protocol) so the fix gets a permanent regression scenario; when
  adding a new failure mode to test (crashes, drains, zombies, lag, failover);
  or when a new correctness property needs asserting during runs. Trigger
  terms: personhog gate, chaos scenario, test harness, leader path regression,
  handoff bug, eviction, writer lag, acked write.
---

# Extending the personhog test harness

The harness (`rust/personhog-test-harness/`, see its README for usage) spawns a
real personhog stack and asserts one invariant three ways: **every acked write
is visible afterwards** — live via read-your-write probers, at end-of-run via
strong reads, and durably via Postgres at the acked version. It has caught real
bugs (eviction data loss, unordered lifecycle shutdown, coordinator failover
stalls) precisely because chaos scenarios run against those assertions.

## When to add a scenario

Add one whenever you fix a personhog bug whose _trigger_ the harness can
reproduce — a crash, drain, restart, lag, election, or eviction condition. The
fix's PR should show the scenario red before the fix and green after; that run
becomes the permanent regression test. Also add one when introducing a new
failure mode (a new process to disrupt, a new timing window) or a new
correctness property (a new journal check).

Don't add scenarios for behavior already covered by an existing flag
combination — compose existing flags instead — and don't add unit-testable
logic here: the harness is for whole-stack behavior only.

## Where things live

- `src/cli.rs` — every scenario is driven by `GateArgs` flags.
- `src/scenarios/gate.rs` — `ChaosEvent` enum, `chaos_timeline()` (offset-sorted
  events, paired stop/resume events), the dispatch loop, and verification
  ordering (probers → regressions → strong reads → Postgres quiesce).
- `src/stack/mod.rs` — stack primitives: spawn/kill/restart leaders (SIGKILL,
  SIGTERM drain, SIGSTOP/SIGCONT zombie), writer crash/pause, coordinator
  kill, etcd lease revocation, per-service env. New disruptions are new
  methods here.
- `src/state.rs` — the acked-write journal and its verifiers. New invariants go
  here, and their decision tables get unit tests: a false-negative verifier
  looks identical to a healthy stack, so e2e runs cannot reveal it.
- `README.md` — every scenario gets a runnable example; scenarios that stay red
  because of a known unfixed defect go in the "Known defects" section with
  their observable signature and fix direction.

## Adding a chaos scenario

1. Add the stack primitive if the disruption is new (prefer process signals
   and etcd operations; never disrupt the shared docker containers — they
   also serve the dev stack).
2. Add the `GateArgs` flag, the `ChaosEvent` variant, and its
   `chaos_timeline()` entry. Timed events take an offset; paired disruptions
   (pause/resume) schedule both entries. State-triggered events (like
   `--kill-handoff-target`) poll etcd after their triggering event instead.
3. Guard invalid combinations in `gate.rs` with an early `bail!` (for example,
   coordinator kill requires two routers).
4. Rehearse locally until deterministic — three consecutive green runs is the
   bar (see the README for build and docker prerequisites). If timing makes a
   scenario a lottery, make it deterministic (the coordinator election is
   forced at bring-up for exactly this reason) rather than accepting flakes.
5. Only failed-but-unacked requests are tolerable during chaos; the invariant
   machinery needs no changes for a new disruption unless you're adding a new
   _property_, in which case journal it in `state.rs` with unit tests.
6. Add the scenario to the `personhog-gate` CI job in
   `.github/workflows/ci-rust.yml` once rehearsed — extend an existing
   composite run if compatible (keep runs to roughly three disruption kinds so
   failures stay diagnosable), or add a step. Expected-red scenarios
   (documenting a known defect) stay out of CI until the defect is fixed.

## Validating a fix with the harness

Run the harness binary against binaries built from the fix branch:

```bash
cargo build -p personhog-replica -p personhog-router -p personhog-leader -p personhog-writer
personhog-test-harness gate <scenario flags> --bin-dir <fix-worktree>/rust/target/debug
```

Show the same command red on the base branch and green on the fix in the PR's
testing section.
