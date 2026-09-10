# Compromises

Deliberate scope cuts on in-flight work, with the follow-up they imply.

## Account tag workflow trigger: no loop detection or throttling yet

Workflow-driven tag adds intentionally emit `$account_tag_added` so workflows can chain (e.g. MRR-threshold workflow tags the account → tag-triggered workflow emails the CSM). The flip side: two workflows whose actions add/remove each other's trigger tags (`tags_mode: set`/`remove` deletes rows, so re-adding fires again) can loop indefinitely, rate-limited only by workflow execution latency. Nothing detects or breaks such cycles today — the runtime's step cap is per-invocation and its dedup is per-event-uuid, and each loop iteration is a fresh event.

Events already carry the attribution a guard needs (`actor_type: "workflow"` + `workflow_id`, forwarded via the `X-PostHog-Hog-Flow-Id` header from the CDP worker). Follow-up options, in rough order of value:

1. **Static pre-save warning:** `HogFlow.trigger` and `HogFlow.actions` are JSON, so a per-team graph (edge A→B when A's `template-posthog-update-account` action writes tags intersecting B's trigger tags) can be cycle-checked on save/activate. Templated tag inputs (`{event.properties...}`) force conservative "any tag" edges, so this should warn, not block.
2. **Runtime backstop:** a chain-depth property incremented when a workflow-attributed event triggers another workflow (cap at N hops), or a throttle keyed on `(account, tag, workflow)`.

## Account tag events: emission blocks the request thread post-commit

`$account_tag_added` and `$account_tag_removed` are emitted synchronously inside `transaction.on_commit` in `facade/api.py`. Each event type uses one batched `capture_batch_internal` HTTP call after the group-type lookup, which Redis caches. The degraded case blocks the request for up to the two-second timeout times retries when capture-rs is slow or down. A Celery offload was tried and reverted (`b6c62469ee9`) because tag changes are infrequent and conversation ticket events use the same pattern.

Revisit if account tagging becomes bulk/high-frequency (e.g. CRM syncs tagging thousands of accounts). Cheapest fixes then: cap the worst case (`timeout=1, max_attempts=1` — drops instead of retries during a blip), or prebuild the payload in-request and POST from a small module-level thread pool so no ORM touches the worker thread.
