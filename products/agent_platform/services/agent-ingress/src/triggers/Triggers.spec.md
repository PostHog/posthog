# Triggers

Inbound trigger modules — each ships one self-describing route list from which mounting, guards, schema publication, and auth advertisement all cascade. The edge semantics every module must share (content-type robustness, drop semantics, dedup, signing fail-closed) are a checked contract, not a convention copied from the previous trigger.

## invariants

- trigger-edge-conformance

## works when

- typechecks
- boundary "trigger-edge-conformance" at TRIGGER_MODULES via test "trigger-module conformance suite"

## why

trigger-edge-conformance: every new trigger historically re-learned the same edge bugs by copying its predecessor — a urlencoded-mislabeled body passing signature verification but silently dropping or corrupting the event, allowlist misses answered with provider-hostile 4xx (recorded as failed deliveries and retried), dedup silently disabled when the delivery-id header is absent, and fail-open when a signing secret is unresolved. The conformance suite iterates the live `TRIGGER_MODULES` registry and requires a fixture per module (the ratchet: registering a trigger without conformance fixtures is a red build naming the type), then asserts each applicable edge class through real HTTP responses and observed enqueues. Assertions are exact-match on seed content, not substring — a garbled-but-overlapping payload must still fail.
