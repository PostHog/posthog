# Jev decisions in HogQL

`prompt_jev` evaluates text using the PostHog-hosted Jev model through the Go AI gateway.
It supports yes/no probabilities and classification into a fixed set of labels.
The implementation follows the SQL decision workflow in [MotherDuck's prompt_jev reference](https://motherduck.com/docs/sql-reference/motherduck-sql-reference/ai-functions/prompt-jev/), with the differences below.

## Enable the experiment

Set these server environment variables:

- `HOGQL_PROMPT_JEV_ENABLED=true` (disabled by default).
- `AI_GATEWAY_URL`: the Go gateway's HTTPS base URL.
- `AI_GATEWAY_API_KEY`: a server credential with `llm_gateway:read` and access to `posthog/hogference/jevk5-fp8-0.2`.

The gateway charges the wallet that owns this credential.
The requesting team's ID and the user's distinct ID label the request; those labels do not change the paying wallet.
Enable this only for an experiment whose model spend the credential owner has agreed to cover.
There is no TypeSafe fallback, and no model key belongs in SQL.

## Query examples

Without criteria, the result is the probability that the statement holds, between 0 and 1:

```sql
SELECT prompt_jev('Please refund this purchase.', 'Does this request a refund?') AS refund_probability
```

Use `choice` for a label, confidence, and the probability distribution:

```sql
SELECT result.choice, count() AS messages
FROM (
    SELECT prompt_jev(
        body,
        'Classify the subject of the message.',
        choice := ['billing', 'technical', 'other']
    ) AS result
    FROM (
        SELECT properties.message AS body
        FROM events
        WHERE event = 'support_message' AND timestamp >= now() - INTERVAL 1 DAY
        LIMIT 100
    )
)
GROUP BY result.choice
ORDER BY messages DESC
```

A choice result is a named tuple with `choice`, `probabilities`, and `confidence` fields.
Each item in `probabilities` has `value` and `probability` fields, in the order of the supplied labels.

Filter a probability in an outer query:

```sql
SELECT refund_probability
FROM (
    SELECT prompt_jev('Please refund this purchase.', 'Does this request a refund?') AS refund_probability
)
WHERE refund_probability > 0.8
```

## Execution and limits

Place each call directly in a SELECT column with an explicit alias.
The input SELECT runs through the normal HogQL resolver and access checks.
The executor evaluates its text inputs and sends the resulting rows back to ClickHouse as query-scoped external data.
Outer queries can filter, join, sort, and aggregate those results without repeating inference.
A CTE referenced twice uses the same computed decisions.
Results are not persisted across executions.

- A classification SELECT reads at most 1,000 rows. Add a literal `LIMIT` to choose a smaller sample.
- Identical text and question configurations share a decision within one execution.
- A query allows at most 1,000 distinct decisions and 2 MiB of unique input text.
- Each text input is at most 8 KiB. Instructions are at most 8 KiB; each label is at most 1 KiB.
- Choice accepts 2 to 16 unique, non-empty string labels.
- `batch_size := N` accepts 1 to 32 and defaults to 16. Batches also respect a 32 KiB text budget. At most four requests run concurrently.
- Batching shares model context across inputs. Use `batch_size := 1` when each input must be evaluated separately.
- The model stage has a 60-second budget, with individual HTTP timeouts capped at 30 seconds.
- NULL input sends no request. A yes/no call returns NULL; a choice call returns `(NULL, [], NULL)` because ClickHouse cannot wrap a tuple in Nullable.
- Configuration errors, invalid input, budget exhaustion, and model request failures fail the query. Failures are not silently treated as negative classifications.

## Differences from MotherDuck

This experiment supports `noul` and `choice`, with string labels.
It does not support `score`, label descriptions, `questions`, or arbitrary JSON question definitions.
The supported model is PostHog's hosted JevK5, not TypeSafe's `jev-latest`.

Use an outer query for expressions over decisions, filtering on decisions, grouping, sorting, or DISTINCT.
List columns explicitly in the classification SELECT; `*` is not supported there.
Direct connections and queries compiled for embedding or materialization do not support the function.

## Validation

Run from the repository root with its own prepared environment:

```sh
.codex/with-flox hogli test posthog/hogql/test/test_prompt_jev.py
```

The integration tests use real ClickHouse and Postgres and stub only the model's HTTP response.
A live smoke test additionally needs the gateway settings above and should use synthetic text.
