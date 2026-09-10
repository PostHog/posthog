# Signal processing costs

Signals accumulate costs during processing, before their first ClickHouse publication.
There is no cost lookup against product analytics and no later cost-update write to ClickHouse.

```json
{
  "token_cost": { "research": 12, "implementation": 0 },
  "compute_cost": { "research": 0, "implementation": 0 }
}
```

Every amount is an integer number of cents.
`research` includes emission checks, safety, grouping, repository selection, and research.
An implementation run charges only the signal that triggered it, not every signal in the report.

## Pricing

`signal_costs.token_usage_to_spend` maps returned token usage to cents using the gateway model catalog.
It accounts for uncached input, output, cache reads, and cache writes.
Catalog rates remain strings; Decimal arithmetic is local to that conversion.
Each response rounds to the nearest cent, with halves rounded up.
Only integer cents enter signal metadata or cross a stage boundary.

`normalise_cost(model, spend)` is a passthrough hook for future pricing policy.
`add_cost` applies it when recording spend; `merge_costs` combines amounts that were already normalized.
Validation retries count every returned model response, not just the final accepted response.
The catalog cache expires after one hour, and an unpriced model raises rather than silently reporting zero.

`TaskRun.get_current_spend()` is deliberately a placeholder returning zero token and compute cents.
Repository selection, research, and implementation call it through the Tasks facade.
Task-backed costs therefore remain zero until runtime accounting replaces the placeholder.
No task-runtime instrumentation or database fields are added.
Embedding API usage is not priced by this mapping.
Publication reuses the canonical vector prepared during grouping, rather than requesting another embedding.

## Handoffs

- Grouping assigns the signal to its report before choosing the next destination.
- A signal that triggers research goes to `signals/processing/<team_id>/<signal_id>.json` in object storage.
- A signal that triggers no further work publishes directly to ClickHouse with its accumulated metadata.
- Arrivals during active research also wait in S3 until Temporal can decide whether they cross the next research bucket.
- Research combines the report's existing ClickHouse signals with its S3 handoffs, then saves updated costs to S3.
- A detached finalizer waits for an implementation workflow to complete, including cleanup, before adding its spend and publishing.
- If there is no implementation, the finalizer publishes after research ends.

Temporal's in-flight registry stores S3 keys rather than copies of signal payloads or vectors.
Grouping includes in-flight handoffs in semantic matching, so later batches can find reports whose triggering signals have not published yet.
The grouping workflow carries those keys across `continue_as_new`, including idle runs.
A finalizer releases a key only after ClickHouse confirms the signal is visible.
S3 objects remain available for retries and overlapping research snapshots.

The first promotion, ordered by its assigned signal count, owns the initial research pass's cost.
A later pass charges the handoff that crosses the next research bucket.
Other signals covered by a pass keep their own earlier costs.
Arrivals below the next bucket publish without another research pass.
Implementation runs carry their owning handoff key in existing run state, so an activity retry can recover the same run without charging another signal.

Task costs are added once per task ID within a handoff.
Later manual runs do not revise an already-published signal's costs.
Final publication preserves the signal ID and timestamp and records an S3 publication marker after Kafka acknowledges delivery.
Delivery retries can repeat the same final record, but do not calculate new costs or buy new embeddings.
Unsafe or deleted reports publish deleted signal metadata so their content stays out of semantic matching.

## Temporal compatibility

`signals-stage-handoffs-v1` gates the new workflow commands and handoff behavior.
Histories without that patch retain the original emission and summary path.
New activity fields have defaults for payloads written before this change.
The summary tests record a patch-disabled history and replay it against the current workflow implementation.
