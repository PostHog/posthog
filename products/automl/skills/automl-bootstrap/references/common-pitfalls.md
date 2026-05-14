# Common pitfalls

Failure modes that have come up in real bootstrap runs. Read this when
something errors — there's a decent chance the answer is here, and you can fix
and retry without giving up the run.

## HogQL `AND ... BETWEEN ...` operator precedence

**Symptom:** `prepare-from-hogql` exits 1 with a body like:

```text
{"type":"validation_error","code":"illegal_type_of_argument",
 "detail":"Illegal type (DateTime64(6, 'UTC')) of 2 argument of function and:
   In scope SELECT ... and(equals(e.event, 'X'), toTimeZone(e.timestamp, 'UTC')) >= s.signed_at ..."}
```

**Cause:** HogQL parses

```sql
e.event = 'X' AND e.timestamp BETWEEN s.signed_at AND s.signed_at + INTERVAL 14 DAY
```

as

```sql
(e.event = 'X' AND e.timestamp) BETWEEN s.signed_at AND s.signed_at + INTERVAL 14 DAY
```

— the `AND` binds tighter than `BETWEEN`, so `e.timestamp` gets consumed by
the boolean, and the comparison `>= s.signed_at` is then applied to a boolean
(a `DateTime64` is being compared to that boolean — hence the error).

**Fix:** parenthesize the `BETWEEN`:

```sql
e.event = 'X' AND (e.timestamp BETWEEN s.signed_at AND s.signed_at + INTERVAL 14 DAY)
```

Apply the same fix to every `... AND <col> BETWEEN ...` and every `IS NOT NULL
AND <col> BETWEEN ...` in your query. Then re-run `prepare-from-hogql`.

## `config.target` vs `config.target_event`

These are deliberately different concepts and the task description's pipeline
spec has both:

- `config.target_event` is the **PostHog event name** (e.g., `upgraded_plan`).
  The validator uses it for base-rate sizing and leakage checks before the
  pipeline runs.
- `config.target` is the **column name in the training snapshot** (e.g.,
  `target`, or `upgraded_in_14d`). The trainer uses it as the label column.

Your SELECT clause must produce a column named exactly `config.target`. The
`--target` flag on `automl train` takes the column name (the second one), not
the event name.

**Symptom:** `train` exits 1 with `KeyError: <target>` or "target column not
found in dataframe".

**Fix:** add an `AS target` (or whatever `config.target` is set to) on the
label expression in the SELECT clause, or rename the existing label column.

## Empty / too-few rows in the snapshot

**Symptom:** `prepare-from-hogql` returns successfully but `rows` is 0 or
below the 200-row training floor.

**Causes (try in order):**

1. **Horizon-eligibility filter excludes everyone.** A query like
   `WHERE signed_at <= now() - INTERVAL 14 DAY` will exclude all users if your
   demo data is recent. Sanity-check by running the same SELECT without the
   horizon filter via the HogQL API directly — if the count is high enough
   without the filter, your test data isn't old enough for that horizon.
2. **JOIN keys mismatch.** A `LEFT JOIN events e ON e.person_id = s.person_id`
   that produces 0 matching rows means `person_id` is structured differently
   between the two sides. PostHog's `person_id` is a UUID; if one side
   accidentally projects `distinct_id` or `uuid`, you'll get an empty join.
   Inspect with `SELECT count() FROM events e JOIN <subquery> s ON ... LIMIT 1`.
3. **The target event genuinely doesn't fire often.** Confirm with
   `SELECT count(), countDistinct(person_id) FROM events WHERE event = '<target_event>' AND team_id = <id>`.
   If the count is structurally low (e.g., the demo data only has a handful of
   conversions), bootstrap isn't recoverable — surface the count and stop.

## Leakage features

Some features will leak the target. Examples:

- A `paid_bill` event scheduled to fire after `upgraded_plan` is a perfect
  predictor of `upgraded_plan`. The trainer will hit ~1.0 accuracy and the
  user will think the model is great when actually it's just memorizing the
  causal chain.
- A property that's only set after the conversion event (`account.plan` = the
  upgraded plan name).

The pipeline config carries `excluded_features` for this reason — patterns like
`paid_bill_*`, `upgraded_plan_*`. **The CLI does not filter features by these
patterns yet** — you have to exclude them in your SELECT clause. If you see a
training run with suspiciously high accuracy (>0.95 on a real-world problem),
suspect leakage first.

## Untagged-query errors from the HogQL API

**Symptom:** the HogQL API returns a 500 with a `UntaggedQueryError` mention.

**Cause:** PostHog requires every ClickHouse query to be tagged with a
`product` + `feature` for observability. The `prepare-from-hogql` path goes
through the public `/query/` endpoint which does its own tagging — you should
not hit this. But if a validator-style code path is also being called and it
isn't tagged, it'll fail this way.

**Fix:** this is a server-side bug, not a sandbox bug. Surface the trace in
your outcome report and stop.

## Sandbox-credential issues

**Symptom:** `prepare-from-hogql` gets a 401 from the HogQL API.

**Cause:** the `POSTHOG_PERSONAL_API_KEY` env var has expired, was issued for
a different team, or is missing the `automl:read` / `automl:write` scope.

You cannot recover this from inside the sandbox — the key is OAuth-issued at
sandbox provisioning. Surface the 401 body in your outcome report and stop.
