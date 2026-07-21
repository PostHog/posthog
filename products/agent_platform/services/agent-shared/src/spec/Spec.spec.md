# Spec

The agent spec schema (`AgentSpecSchema`, zod) — the single source of truth for the `revision.spec` JSONB — plus the codegen bridge that emits spec vocabularies as checked-in JSON for the Django control plane to import.

## invariants

- tenant-array-bounds
- generated-vocabulary-single-source
- trigger-routes-single-source

## works when

- typechecks
- boundary "tenant-array-bounds" at AgentSpecSchema via test "agent spec tenant-array bounds"
- boundary "generated-vocabulary-single-source" at GENERATED_ARTIFACTS via test "spec generated artifacts"
- boundary "trigger-routes-single-source" at TRIGGER_ROUTES via test "spec generated artifacts"

## why

tenant-array-bounds: every top-level array in the spec is author-controlled and flows into a loop/query at freeze/promote/run, so an unbounded one is a resource lever (the confirmed case: `identity_providers` fanning out into per-entry OAuthApplication creation + org-row locks at promote). The oracle reads the schema's own JSON-Schema projection, resolves `$ref` and walks `anyOf`/`oneOf`/`allOf` so a `nullable`/union array can't slip through undetected, and asserts a FLOOR on how many array fields it finds — if the projection shape ever changes so it detects fewer, the floor fails loud instead of the oracle passing vacuously (the false-green class this exists to prevent).
generated-vocabulary-single-source: the vocabularies Django needs as data (per-trigger required secrets, approval-request states, assistant stop reasons) are authored once here and emitted as checked-in JSON that Django imports, so there is no hand-maintained Python copy to keep in lockstep. The freshness oracle welds each checked-in artifact to its TS source (parsed comparison, formatter-immune); a registry-non-empty floor keeps the guard from passing vacuously if the artifact list ever collapses. Coverage that the guard actually runs on artifact edits is enforced CI-side (`test_ci_guard_coverage.py`).
trigger-routes-single-source: the per-trigger ingress route catalogue is authored once in `TRIGGER_ROUTES` (total over `TriggerType`; `cron` explicitly empty — janitor-fired, no inbound route). The ingress trigger modules import their `path:` values from it and Django's preview-endpoint builder reads the emitted artifact, so the routes the ingress actually serves, the paths previews advertise, and the trigger-kind enumeration strings cannot drift — retiring a hand-mirror that its own comment asked readers to "keep in sync" and that contributors measurably missed.
