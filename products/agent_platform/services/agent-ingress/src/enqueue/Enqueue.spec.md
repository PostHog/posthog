# Enqueue

Single-caller-facing auth resolution (identity vs. credentials split, per-mode
verifiers) plus the one place every trigger creates or resumes an
`AgentSession` — `enqueueOrResume`. Session ACL enforcement (`acl.ts`) sits
between the two: it decides whether an incoming principal may advance an
existing session.

## invariants

- shared-secret-single-principal
- enqueue-idempotency

## works when

- typechecks
- boundary "shared-secret-single-principal" at sharedSecretVerifier
- passes test "yields a single team-scoped principal"
- boundary "enqueue-idempotency" at enqueueOrResume
- passes test "returns the original session id on a duplicate call"
- passes test "unique-violation on insert resolves to the original session id"

## why

shared-secret-single-principal: `shared_secret` auth is single-principal by design — every holder of an agent's shared secret is the same trust principal, because nothing behind the secret can forge-resistantly distinguish one holder from another. `x-external-key` is a session-routing tag (dedupe/resume key), never a credential, and `principalsMatch`'s `shared_secret` arm discriminates only on `team_id`. Adding any per-caller header, claim, or discriminator behind the secret creates a false boundary — any other holder of the same secret can self-assert the same header — and this exact mistake shipped and was reverted twice (a spec-level `caller_id_header`, then a follow-up `x-posthog-caller-id` header; both undone once review caught that either construction defeats the ACL it appears to add). Per-caller isolation is `jwt` mode's job (its `sub` is upstream-signed, not self-asserted); the sanctioned path for continuity-with-isolation under `shared_secret`, if a real use case ever needs it, is server-issued unguessable resume tokens, not a self-asserted header. The oracle pins the mint site so a future patch that reads a caller-asserted header back into the principal fails the assertion instead of silently reopening the hole.
enqueue-idempotency: `enqueueOrResume` runs the idempotency check before the `externalKey` resume path — `findByIdempotencyKey(application.id, idempotencyKey)` short-circuits a duplicate call to the original session id, deliberately discarding the incoming principal and seed message (Stripe-shaped semantics: same request, same result, no side effect replayed). The unique index on `(application_id, idempotency_key)` is the safety net for the window between that pre-check and the `INSERT`: a concurrent writer landing first raises a Postgres unique-violation (SQLSTATE `23505`), which `enqueueOrResumeInner` catches and resolves by re-querying `findByIdempotencyKey` rather than surfacing a raw constraint error or letting the caller believe it created a fresh session. Without both halves, a redelivered webhook (e.g. a provider's `Idempotency-Key` header) racing another delivery of the same event would either duplicate a session's side effects or break the trigger with an unhandled DB error. Both oracles run against real Postgres via `PgSessionQueue` — the race test wraps the queue in a `Proxy` that reproduces the actual timing window (pre-check sees nothing, insert then hits the real unique-violation code) rather than mocking the outcome.
