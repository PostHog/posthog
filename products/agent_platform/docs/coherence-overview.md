# Coherence in the agent platform

Orientation for this stack: what we set out to do, and the concrete boundaries we built.
Every invariant below is declared as a coherence `boundary` — an invariant welded to a
chokepoint symbol and an oracle — so `coherence log --strict` reds the build if any is
renamed, deleted, or left unanchored ("can't ship a half-boundary"). For the method behind
this — the doctrine and the harness that checks it — see
[coherence-onboarding.md](coherence-onboarding.md).

## The goal

A recurring bug is a **structural question answered at call sites** — "did we cover every
sink?", "does this need approval?", "is this the owner?" — re-decided by hand at each site,
so one forgotten site is a latent tear. The cure is always the same move: promote the
convention to a **contract**:

> one declarative **home** (data, not memory) → **derive** every gate from it → enforce at
> the single **chokepoint** all paths cross → **fail closed** → **assert totality** so the
> absence of holes is _checked, not hoped_ → and where it matters most, make the unsafe
> state **unrepresentable** in the type system.

Rigor is graded — **enshrined** (can't compile) > **totality-checked** (an oracle proves the
N sites agree) > **convention** (a doc you hope people read) — and the target is to leave
**no security rule at the convention tier**.

## The bug-shapes we targeted

The stack is organized around the classes that actually recur in this codebase:

1. **Fail-open defaults** — `.get(type, [])`, `requires_approval` defaulting false: the
   permissive answer fires exactly when knowledge is absent.
2. **Wrong-layer authorization** — enforcing at the convenient layer (team) instead of the
   invariant's layer (the credential's owner) → IDOR.
3. **Hand-mirror drift** — a TS enum and a Python list maintained separately, silently
   diverging.
4. **Untrustworthy oracles** — a green test that is vacuous (empty domain), tests a _proxy_
   (a fake DB pool asserts the arg was _passed_, not that the SQL actually filters), or never
   _runs_ (a CI path-filter gap).
5. **Silent drops** — a content-type mislabel or an unregistered trigger swallowed with no
   trace.

## What we built — 25 boundaries across 6 roots

### A. Wrong-layer authorization — enforce at the invariant's layer, not the convenient one

| Boundary                          | Anchor                 | Oracle                                                  | Shrieks when…                                                                                                                  |
| --------------------------------- | ---------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `connection-owner-isolation`      | `PgMcpConnectionStore` | test _"cannot return owner B"_                          | the shared-MCP-credential lookup stops scoping to the spec author — IDOR, proven with real two-owner SQL (not a fake pool)     |
| `connection-bearer-single-reader` | `PgMcpConnectionStore` | guard _"reads of sensitive_configuration are confined"_ | any module other than the store reads the credential column (the owner check is only complete if the store is the sole reader) |
| `team-api-key-isolation`          | `PgTeamApiKeyResolver` | test _"returns only its own api_token"_                 | the `WHERE id = $1` is dropped/inverted and a sibling team's `phc_` token leaks                                                |
| `shared-secret-single-principal`  | `sharedSecretVerifier` | test _"yields a single team-scoped principal"_          | a per-caller identity is smuggled into `shared_secret` mode (forgeable behind the secret)                                      |

### B. Fail-open → fail-closed / can't-omit

| Boundary                           | Anchor                     | Oracle                                          | Shrieks when…                                                                                     |
| ---------------------------------- | -------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `unregistered-trigger-fail-closed` | `missing_required_secrets` | test _"…fails_closed_on_unregistered_trigger"_  | the old `.get(type, [])` returns — an unknown trigger promotes with its signing secret unenforced |
| `native-tool-approval-floor`       | `nativeToolApprovalClass`  | test _"native tool authorization accessor"_     | a tool ships without a declared `approval` class — a compile error (required field)               |
| `gated-dispatch-single-path`       | `gateTool`                 | test _"gate chokepoint — fail-closed dispatch"_ | any tool reaches the loop unbranded — `assertToolsGated` throws at boot                           |
| `approval-authority-totality`      | `effectiveApprovalType`    | test _"approval-authority totality"_            | a new approval-type enum member isn't handled (total over the enum)                               |

### C. Single-source — one derived thing, no drift

| Boundary                             | Anchor                     | Oracle                                                       | Shrieks when…                                                                        |
| ------------------------------------ | -------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| `generated-vocabulary-single-source` | `GENERATED_ARTIFACTS`      | test _"spec generated artifacts"_                            | a checked-in JSON drifts from its TS source                                          |
| `trigger-routes-single-source`       | `TRIGGER_ROUTES`           | test _"spec generated artifacts"_                            | the TS route map and the emitted JSON disagree                                       |
| `approval-state-vocabulary`          | `APPROVAL_REQUEST_STATES`  | test _"spec generated artifacts"_                            | the runner's states and the DRF/DB copy diverge                                      |
| `generated-vocabulary-loader`        | `_load`                    | test _"…vocabularies_load_and_are_nonempty"_                 | Django loads a corrupt / missing / wrong-shape artifact instead of failing closed    |
| `artifact-ci-coverage`               | `TRIGGER_REQUIRED_SECRETS` | test _"…filter_covers_every_generated_artifact"_             | a generated artifact escapes the CI path-filter (the _guard-must-be-run_ meta-check) |
| `gateway-wire-single-source`         | `extractGatewayRequestId`  | test _"request id single-sourcing"_                          | dispatch and cost-lookup key on two different ideas of "the request id"              |
| `approval-wire-resolved`             | `serializeApprovalRequest` | test _"resolves a legacy approvers"_                         | an approval is serialized outside the one shared serializer                          |
| `approval-wire-consumption`          | `buildJanitorApp`          | guard _"approval routes never bypass the shared serializer"_ | a janitor route serializes an approval by hand                                       |

### D. Make the unsafe _value_ unrepresentable

| Boundary                        | Anchor                    | Oracle                                              | Shrieks when…                                                                                                                          |
| ------------------------------- | ------------------------- | --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `gateway-cost-provenance`       | `assertGatewayProvenance` | test _"cost provenance guard"_                      | a non-gateway (or negative/blank) cost reaches analytics                                                                               |
| `direct-http-capability-divide` | `DirectHttpClient`        | guard _"does NOT accept a proxyUrl in its options"_ | the no-proxy internal client gains a `proxyUrl` hatch or is threaded onto agent-reachable context (class identity _is_ the capability) |
| `django-fernet-interop`         | `EncryptedFields`         | test _"urlsafe regression"_                         | the runner can't decrypt exactly what Django encrypted (urlsafe-base64 mismatch)                                                       |

### E. Bounds & edge-totality on inputs

| Boundary                   | Anchor            | Oracle                                    | Shrieks when…                                                                                       |
| -------------------------- | ----------------- | ----------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `tenant-array-bounds`      | `AgentSpecSchema` | test _"agent spec tenant-array bounds"_   | a tenant array ships without `maxItems` (incl. `anyOf`-wrapped nullable arrays)                     |
| `trigger-edge-conformance` | `TRIGGER_MODULES` | test _"trigger-module conformance suite"_ | a trigger regresses content-type / drop / dedup / signing (with double-entry over the edge classes) |

### F. Liveness — nothing gets stuck, nothing mutates after seal

| Boundary                     | Anchor                   | Oracle                                                                                                | Shrieks when…                                                |
| ---------------------------- | ------------------------ | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `freeze-validate-lockstep`   | `validateRevisionBundle` | tests: missing entrypoint / unknown tool / unserved model / client-tool-with-webhook / malformed cron | the janitor freezes something the runner would reject        |
| `sweep-bounded-retries`      | `sweepOnce`              | test _"poison-pills a stuck running session after maxRetries"_                                        | a stuck session isn't reaped after `maxRetries`              |
| `bundle-freeze-immutability` | `S3BundleStore`          | test _"freezes and blocks further writes"_                                                            | a live revision's frozen bundle is written again             |
| `enqueue-idempotency`        | `enqueueOrResume`        | test _"returns the original session id on a duplicate call"_                                          | a redelivered event doesn't collapse to the original session |

**Density:** `agent-shared` carries 14 (the shared substrate is where cross-tenant and
single-source invariants concentrate); the rest spread across ingress, runner, janitor,
tools, and the Django backend. Every root also declares `typechecks` as its tier-0 floor.

The oracles are kept honest by **defect injection**: every boundary was proven to go _red_
when the invariant is violated — the only check that tests semantics, not anatomy (a green
oracle can be a proxy; a passing meta-oracle can't tell).

## Where we are on the ladder — honestly

- **All 25 render tier-2 today** (totality-checked): declared, oracle-guarded, floored
  against vacuous passes.
- **2 are tier-1-eligible** (the illegal value is structurally _unrepresentable_): the
  required `approval` field, and the no-`proxyUrl` capability divide — which now carries its
  backing `via guard`.
- **Not built yet: the trust-manifold grading layer** — the crossing-by-crossing view that
  would emit a "zero tier-3 security crossings" report and reconcile enshrinement claims.
  That's the next frontier.

## Is this worth it?

The leverage is real but bounded. Coherence catches the _boundary-class_ regressions above —
a deleted `WHERE owner`, a drifted vocabulary, an ungated tool, a vacuous oracle — and makes
the convergent move (add a row to one home) cheaper than the divergent one (add a guard at a
new call site). It catches nothing _outside_ its declared boundaries, and a green run can lull
you there. It earns its place on the security-critical chokepoints; over-applying it —
enshrining everything, essaying every rationale — is its own pathology.
