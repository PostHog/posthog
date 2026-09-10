# Signal costs

Signals store `token_cost` and `compute_cost` in the metadata of their canonical `document_embeddings` row (`text-embedding-3-small-1536`).
Both objects have `research` and `implementation` keys with integer USD cent values.

The signal that triggers work receives its full cost.
Other signals grouped into the report do not share that cost.
Each signal receives its own emission, safety, query-generation, matching, and specificity-check spend.
The signal that promotes a report receives the report safety, repository-selection, and research costs.
Implementation uses the trigger from the research pass that settles the report.
When a running report researches again, the signal that crosses the next research bucket becomes that pass's trigger.
Assignment counts determine this identity, rather than source timestamps or the last signal absorbed during debounce.

## Sources and pricing

Direct model calls carry `triggering_signal_id` on their existing AI observability events.
Research, repository selection, and implementation tasks store the signal ID when the task is created, including runs that fail before returning their first response.
Later runs of the same task retain that attribution.
Deferred implementation starts recover the trigger from the report's latest attributed task.

`token_cost` sums priced `$ai_generation` and `$ai_embedding` events from the regional AI observability project.
A generation matched by both its signal ID and task-run ID is counted once.
The embedding worker does not emit these cost events, so its embedding requests are not included.
`compute_cost` uses the Tasks sandbox-session ledger and compute rate cards, without the customer-billability filters.
This accounting does not change customer charges.

`normalise_cost(model, spend)` receives Decimal USD spend and returns it unchanged.
It is the shared hook for future pricing adjustments.
`add_cost` accumulates normalized spend by stage.
Conversion to cents happens after accumulation, using half-even rounding so sub-cent calls contribute to the total.

## Refresh and recovery

New signals start with zero amounts and `costs_pending: true`.
Grouping emission, report safety, task creation, and task status changes schedule a refresh after a five-minute ingestion grace period.
Grouping queues the refresh before assigning the signal, so an enqueue failure can retry without repeating assignment.
The refresh replaces amounts from source totals instead of incrementing them, so replaying a refresh does not charge twice.
Missing signal rows, unpriced generations, and active or recently completed task runs cause up to twelve further five-minute retries.
Known amounts remain a lower bound while `costs_pending` is true.
A later task transition schedules another refresh even if an earlier retry chain expired.

A metadata refresh copies the existing canonical embedding into the ClickHouse ingestion topic.
It preserves the signal's timestamp, content, and other metadata, and does not request another paid embedding.
The refresh waits for Kafka delivery confirmation before completing.
Reingestion preserves the signal ID, timestamp, and accounting start time.

To repair a projection, enqueue `products.signals.backend.tasks.refresh_signal_costs` with `team_id` and `signal_id`.
Check `signals.cost_update_schedule_failed` and `signals.unpriced_generations` logs when costs remain pending.
Existing signals without `costs_started_at` are not backfilled because their earlier model calls lack signal attribution.
