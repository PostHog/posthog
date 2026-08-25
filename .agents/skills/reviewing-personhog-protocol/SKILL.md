---
name: reviewing-personhog-protocol
description: >
  The full review process for personhog coordination-protocol changes —
  leases, fencing, handoffs, supervisors, failure budgets, warming, and
  changelog semantics. Use before pushing or requesting review on any
  personhog protocol changeset, when asked for an exhaustive or careful
  review of personhog code, and after any reviewer finds a gap the author
  missed. Covers the adversarial two-pass process, the review lens
  dimensions, the model-checking and test layers a change must clear, and
  the red-check-every-fix discipline.
---

# Reviewing personhog protocol changes

Protocol defects survive ordinary review because every component looks
correct in isolation — the bugs live in compositions: an authority signal
nobody observes during one await, a threshold that coincides with a
detector's duration, a rarely-taken exit path that skips the fence. This
skill encodes the process that has actually caught them, and the full set
of layers a personhog change must clear before it ships.

## The process: two passes, then verification

1. **Author pass.** Sweep the full diff against every lens dimension
   below. Read final files, not hunks — composed state is where the bugs
   are.
2. **Independent adversarial pass.** Spawn a cold-context agent on the
   full diff. Give it the protocol invariants
   ([references/personhog-invariants.md](references/personhog-invariants.md))
   and the lens dimensions — never your conclusions or your fixes'
   rationale, which would anchor it. Demand: ranked findings with
   `file:line`, a one-sentence defect statement, a concrete failure
   scenario (inputs/state → wrong outcome), and a CONFIRMED (traced
   end-to-end) or PLAUSIBLE (missing check named) label. Ask it to state
   clean dimensions in one line each — silence is not coverage.
3. **Author verification.** Verify every finding against code before
   accepting it. Findings get upgraded, downgraded, or killed with
   evidence — never adopted on authority. A wrong finding fixed is a new
   defect introduced.
4. **After a fix batch, review again.** Fresh agent, full scope, with the
   fix batch named as the primary attack surface: new code is where new
   bugs live, and a fix can displace a defect instead of closing it. Ask
   for a per-finding CLOSED / DISPLACED / STILL OPEN verdict.

## The lens dimensions

For each, the question to ask — not a checkbox, a hunt:

1. **Authority transitions × in-flight work.** Enumerate every
   writer × key × guard. For each transition of serving authority
   (acquire, release, fence, deregister): what work is in flight across
   it, and what guarantees it lands on the right side? Never dismiss a
   race on likelihood — protocol review argues structure, not odds.
2. **Observation latency.** A prompt failure signal nobody is listening
   to is a deferred fence. Enumerate every await a component makes
   _while holding authority_ (lease, registration, serving state) and
   ask: is the authority-loss signal raced here, or does this await
   defer detection for its full duration? Backoff naps, drains, and
   bootstrap sequences are where this hides.
3. **Timescale interactions.** Build the full constants table (TTLs,
   heartbeats, margins, budgets × intervals, timeouts, deadlines,
   watchdogs, produce/message timeouts) and check pairwise interactions.
   Two smells: a threshold that equals a detector's duration (the
   detector's failures become structurally exempt from the threshold),
   and a margin whose consumer can outspend it (a fence bounded by a
   timeout larger than the runway). Validate required relations at
   construction, not in comments.
4. **Budget and counter semantics.** What resets what, and on which
   evidence? Progress must mean _applied work_ — never a successful
   read, which stays available in exactly the wedges budgets exist for.
   Ask both directions: can a wedge class cycle forever without
   escalating, and can a transient class escalate spuriously?
5. **Lifecycle.** Every spawned task joined or aborted on every exit
   path; raced JoinHandles consumed at most once with every later await
   site guarded; cancel-by-drop assumptions verified (dropping a loop
   future drops its owned futures — but never its spawned tasks);
   teardown ordering stated and tested. The bootstrap window —
   registered but not yet supervised — is an exit-path zoo of its own.
6. **Primitive semantics, verified against implementation.** What does
   the primitive actually do — not what its name suggests? `select!`
   short-circuits on first ready arm; `FuturesUnordered` only progresses
   when polled; a keepalive response proves a reset at send-processing
   time, not receipt time; stream end and lease expiry are different
   facts; etcd answers keepalives for a dead lease with TTL 0, not a
   closed stream. When in doubt, read the dependency's source.
7. **Failure-path parity.** The rarely-taken exits — budget exhaustion,
   timeouts, poison paths, fast-shutdown branches — must uphold the same
   invariants as the hot path. "The fence exists" is not enough; it must
   run on _every_ path that drops authority, in the right order relative
   to deregistration.
8. **Escalation legibility.** Fail loudly _and attributably_: a crash
   cascade that shows up as generic restarts is loud but illegible.
   Every deliberate escalation should carry the specific cause (which
   partition, which budget, which margin) in its metric labels and logs.

## The layers a change must clear

A personhog protocol change is not reviewed by reasoning alone. Check
each layer, in order of cost:

1. **Decision-logic coupling (stateright).** `personhog-stateright`
   model-checks the protocol by driving transitions through the
   production decision functions (`desired_state` and friends). If the
   change touches decision logic, phases, or ack semantics: does the
   model still compile against it, do the existing properties still
   hold, and does the change introduce interleavings the model should
   now cover (a new scenario variant)? Execution-level changes
   (concurrency structure, supervision) don't need model updates — say
   so explicitly rather than silently skipping.
2. **Protocol integration tests** (`personhog-coordination/tests/`,
   real etcd): every behavioral change pinned by a test that fails on
   the old code — see the red-check discipline below. Connection-level
   behavior (blips, outages, lease margins) is testable by routing the
   component's store through a byte-forwarding TCP proxy the test
   controls: sever live connections to simulate a blip, refuse new ones
   to simulate an outage. The test commons' `FlakyProxy` provides this
   (arriving with the etcd-resilience changes); on a tree without it,
   that is the pattern to build — tokio only, well under a hundred
   lines.
3. **The e2e harness gates** (`personhog-test-harness gate`): run the CI
   gate scenarios locally against the built tree — at minimum the
   drain + zombie + writer-lag and kill + scale-up variants, plus any
   scenario shaped like the change. The gates assert the invariant that
   matters: every acked write visible in strong reads and Postgres.
4. **Mixed-fleet compatibility.** Deploys roll pods one at a time: old
   and new binaries share etcd and the changelog mid-roll. Any change to
   etcd record shapes, ack semantics, phase meanings, or changelog
   framing must be read-compatible in both directions across one
   release, or gated. Also check charts interplay: termination grace
   periods versus drain timeouts, lease TTLs versus rollout pacing.
5. **Observability and the residual ledger.** New failure modes need
   counters with attributing labels and, where they change operator
   response, dashboard panels. `rust/personhog-coordination/README.md`
   is the design + residual-risk ledger: update it when a fix changes a
   stated guarantee, and never let a known residual silently widen.
   After deploy, validate on the dev traffic bed: violations zero,
   restarts flat, the change's own metrics moving as predicted.

## Fix discipline

- **Red-check every fix**: temporarily disable the fix (scratch-copy the
  file first — never `git checkout` for temp reverts, it destroys
  uncommitted work), run the new test, confirm it fails for the
  predicted reason, restore, confirm green.
- One regression test per fix, at the lowest level that catches it, per
  `/writing-tests`. If a fix can't be pinned without heavy new machinery,
  say so explicitly in the PR rather than silently skipping.
- Fixes to counters, budgets, or thresholds must state their invariant in
  a comment — the next reviewer checks the invariant, not the arithmetic.

## Related

- `/writing-tests` — the test-worthiness gate for the regression pins.
- `/adding-personhog-rpc` — the data-plane counterpart (RPCs, storage,
  routing); this skill owns the coordination plane.
- `rust/personhog-coordination/README.md` — the protocol's own design and
  residual documentation; review claims against it.
