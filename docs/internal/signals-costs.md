# Signal processing costs

Signals accumulate costs during processing, without retrospective product-analytics queries.
Each stage either hands a signal to the next stage or publishes it with its final costs.

```json
{
  "token_cost": { "research": 12, "implementation": 0 },
  "compute_cost": { "research": 0, "implementation": 0 }
}
```

Every amount is an integer number of cents.
`research` includes emission checks, safety, grouping, repository selection, and research.
Shared report work charges its triggering signal, not every signal in the report.
Failed internal attempts are not passed on to the user.

## Pricing

`signal_costs.token_usage_to_spend` prices accepted responses using the gateway model catalog, including uncached input, output, cache reads, and cache writes.
Catalog rates remain strings; Decimal arithmetic stays local to conversion, with half-up rounding to integer cents.
`normalise_cost(model, spend)` is a passthrough hook applied by `add_cost`; `merge_costs` combines already-normalized amounts.

Catalog requests have a ten-second timeout without SDK retries.
Prices are cached for one hour; failed refreshes reuse cached prices and retry after one minute.
An unpriced model raises rather than silently reporting zero.
Description summarization and actionability checks retry pricing failures through the same backoff and error handling as model-call failures.
If retries are exhausted, summarization truncates the description and the actionability check keeps the signal.
Both call the model only after pricing succeeds.
Embedding API usage is not priced by this mapping.

`TaskRun.get_current_spend()` deliberately returns zero token and compute cents until task runtime accounting implements it.
Repository selection, research, and implementation use that interface through the Tasks facade.
A shared handoff helper records each task's spend once.

## Publication and handoffs

- Grouping assigns the signal to a report, then either emits it through the embedding worker or writes an S3 handoff.
- Handoffs live at `signals/processing/<team_id>/<signal_id>.json` and carry signal data and costs, not embeddings.
- Research reads ClickHouse context plus its explicitly submitted handoff keys. Handoff data wins over duplicate ClickHouse rows.
- The first promotion, ordered by assigned signal count, owns the initial research cost. Later passes charge the signal crossing the next research bucket.
- An implementation run carries its owning handoff key in protected run state. Only its run ID crosses back into workflow history.
- One finalizer activity checks implementation status, records spend, and publishes when the workflow closes. Otherwise it returns and the workflow waits one minute.
- Signals without implementation work finalize in batches of up to 20, separately from the implementation owner.

Grouping uses the existing best-effort visibility wait only for immediate emissions.
It does not wait for research or implementation, so later batches can miss earlier unpublished signals.
Within-batch matching still uses in-memory context; there is no pending-handoff registry or S3 search overlay.

Final publication preserves the signal ID and original assignment timestamp and sets the handoff's `finalized` marker.
Unsafe or deleted reports publish deleted signal metadata.
All publication goes through the embedding worker; finalizers do not wait for ClickHouse visibility.
Add an object-storage lifecycle rule before rollout to expire `signals/processing/` handoffs after a few days.

## Temporal compatibility

`signals-stage-handoffs-v1` preserves the original emission and summary command path for histories without the patch.
Activity fields have defaults for older payloads; abandoned pre-release handoff formats have no compatibility layer.
