# The AI detector for insight alerts

The `llm` detector type asks a model to judge an insight's recent series instead of fitting a
statistical test to it.
It ships behind the `alerts-llm-detector` flag.

Every other detector is a statistical test that runs locally and costs nothing per check.
This one makes a charged model call on every check, so most of its rules exist to bound that cost.

## What an author configures

An alert author picks "AI judgment" in the detector list and sets:

| Setting             | Default   | Notes                                                                          |
| ------------------- | --------- | ------------------------------------------------------------------------------ |
| Instructions        | none      | What counts as unusual for this metric, in plain words. Up to 2000 characters. |
| Confidence to alert | 0.7       | The confidence the model must report before the alert fires.                   |
| Window              | 90 points | How many recent points the model is shown. Maximum 400.                        |

Each check sends the recent series as a table, a rendered chart of the same points, a description of
the metric, and the author's instructions.
The model returns a verdict: whether the series is anomalous, its confidence, a kind
(spike, drop, flatline, trend break, level shift, pattern change), a short rationale shown to the
person, and which points it flagged.

Changing the detector configuration resets the alert state and schedules a new check.
Metric metadata is escaped and marked as data in the prompt. The chart uses a fixed title.
The prompt describes at most six series, and the alerted series is always one of them.
SQL detector series preserve ISO date and timestamp labels from the selected label column.
The labels follow the same row order and window as the values.
If any label in the window is missing or invalid, the series has no dates and the model receives row positions.

## The number is confidence, not probability

The model reports how confident it is in the verdict it gave, whichever way that verdict went.
It is not calibrated, and it is not comparable with a statistical detector's score.

The shared anomaly score folds the verdict and the confidence into one number:
`confidence` when the verdict is an anomaly, and `1 - confidence` when it is not.
Storing the raw number instead would plot a confident all clear above the threshold, which reads as
a check that would have fired.

Because the fold is not reversible, the check also stores the verdict itself, and the history
classification reads that rather than the folded score.
History with both statistical and AI scores uses a neutral score label.

## When a check fires

A live check fires only when the model names the latest point.
A series with fewer than five points is never sent to the model, and the check stays uncomputed
rather than recording a healthy value.
The check also stores the index of the series it judged, so an investigation that starts after
the alert is repointed still charts the series that fired.
An anomaly verdict about older history records `latest_point_not_flagged` and does not fire, even below the confidence threshold.
Lowering the threshold cannot make that historical check appear to fire for the latest point.
Investigation charts mark the saved check's triggered dates that remain in the chart window.
They do not repeat the model call or mark a newer point in place of the saved anomaly.
The markers still use the saved check after the alert's detector changes.

## What it refuses, and why

| Restriction                            | Reason                                                                                       |
| -------------------------------------- | -------------------------------------------------------------------------------------------- |
| Not available as an ensemble member    | An ensemble scores every sub-detector, so it would add a model call to every ensemble check. |
| Not available on the real-time cadence | The evaluate activity allows about 3 minutes over 2 attempts, which a model call can exceed. |
| Not available on breakdown insights    | One call per breakdown value multiplies the cost of a single check.                          |
| Capped per project                     | The count of enabled AI alerts is the cost ceiling.                                          |
| Needs AI data processing consent       | The series and its metadata are sent to a model provider.                                    |
| Needs the rollout flag                 | Turning the flag off stops the spend.                                                        |

## Cost

Calls per day is the number of enabled AI alerts multiplied by the cadence ticks per day.
On the 15 minute cadence, one alert is 96 calls a day.

The per-project cap comes from `max_llm_alerts_per_team` in the `alerts-llm-detector` flag payload,
and defaults to 5 when the payload does not set it.
A flag rule targeting one organization can carry its own cap.
Only enabled alerts count, and the cap is checked only on a write that adds an enabled AI alert, so
lowering it never blocks an edit to an alert that already exists.

Activity retries can reuse a verdict for 20 minutes. The cache key includes the workflow run and
activity IDs, the series, all prompt fields, the model, and the prompt revision. It stays stable
after the check advances the schedule, but changed model inputs require a new verdict.
AI evaluations use a dedicated thread pool. The routing decision and evaluation use the same
alert configuration snapshot.
Before saving, evaluation locks the current alert, insight, and threshold rows and compares the snapshot.
If the alert changed or was deleted, it discards the result without sending a notification.
The workflow carries the prepared input fingerprint into failure recording.
Exhausted failures and timeouts check it under the same locks before writing,
so they cannot delay an edited alert's first check.
Successful retries retain the shared alert behavior. Durable recovery after a committed activity
loses its completion remains separate work for all detector types.
The next scheduler tick handles an edited alert at its current due time.
An edit between preparation and evaluation can cause one additional retry chain.
The next workflow prepares the current fingerprint and can record an exhausted failure for that configuration.

## Gating

One function, `llm_detector_access_error`, tests the rollout flag and AI data processing consent.
It runs in the simulate endpoint, inside the judge on every scheduled check, and through
`admit_llm_alert_write` in every writer of alerts.

`admit_llm_alert_write` is the single operation the API and the Max tool call for a write that
can put an alert on the AI detector.
It applies the cadence rule, the access check for the alert's creator, and the per-project cap, in
that order, and takes the cap lock only when the write adds an enabled AI alert.
Each writer calls it inside its own transaction after locking the alert row, and renders the typed
refusal in its own error shape.

The last of those is what makes the flag a real stop on spend.
When access is removed, the next check records the cause, disables the alert, and notifies its subscribers.
That notification says the alert was turned off and what to fix; it does not promise a retry.
An unresolved rollout lookup is retryable and leaves the alert enabled.
Evaluation-time disable emails use the notification activity's retries and a stable key for the saved check.
This expected condition does not send an exception to Error tracking.
Restore access and enable the alert to resume checks.

The rollout is checked for the principal the check runs as, which is the alert's creator, not
whoever last edited it.
Privacy mode redacts the prompt and the verdict in AI observability.

## When the model is unavailable

A check that cannot reach a verdict records an error.
It never returns "no anomaly", because an alert that silently stops firing looks healthier than one
that reports a problem.

- A provider failure raises a retryable error, and the retry policy decides. Provider authentication, permission, and model errors do not disable alerts.
- A permanent one, such as withdrawn consent or a missing creator, is not retried.
- The simulate endpoint maps both to HTTP 503.

## Previewing

Simulate runs the detector against an insight without creating an alert or a check.
For the AI type it is a charged call, so it is throttled per project at 10 a minute, 60 an hour and
200 a day, and it refuses breakdown insights before making any call.
The write-scope check runs before these shared limits. A read-only token cannot consume them.
Staff impersonation previews are not billed. Scheduled checks remain billable.
Max validates the current insight configuration for every update that leaves an AI alert enabled.
API and Max updates lock the insight before the alert and validate the locked query definition.
API creation also locks and revalidates the insight before it inserts an AI alert.

The preview judges the whole window in one call, which is not the same shape as a live check.
A live check judges only whether the latest point is anomalous.
The preview describes the date range of the extracted points, including any added history.
Below-threshold anomaly verdicts retain their scores but do not count as triggered anomalies.
Negative verdicts ignore any reported indices. Unscored preview points appear as gaps.
The preview labels AI scores as model confidence. Null scores can be valid unscored points in a completed evaluation.

## Where the code lives

The AI judge is not a `BaseDetector`.
The statistical detectors in `posthog/tasks/alerts/detectors/` score a bare array of values.
The judge reads what the series means and who its charged call runs as, so it has its own contract
in the product: a `SeriesJudge` takes a `SeriesContext` and a `JudgeAttribution` and returns a typed
`SeriesJudgment`, which the evaluation layer reduces to the shared detection result.

| Piece                                    | Path                                                                          |
| ---------------------------------------- | ----------------------------------------------------------------------------- |
| Judge contract, errors, judgment         | `products/alerts/backend/judge/contract.py`                                   |
| Judge, prompt, model verdict             | `products/alerts/backend/judge/`                                              |
| Lookback sizing for the judge            | `posthog/tasks/alerts/detector.py`                                            |
| Chart rendering and metric description   | `posthog/tasks/alerts/charts.py`, `posthog/tasks/alerts/metric_definition.py` |
| Evaluation wiring, breach text, simulate | `products/alerts/backend/evaluation/detector.py`                              |
| Write admission, cap, cadence, access    | `products/alerts/backend/llm_detector_limits.py`                              |
| API                                      | `products/alerts/backend/presentation/views/alert.py`                         |
| Max tool writer                          | `products/alerts/backend/max_tools.py`                                        |
| Editor and history UI                    | `products/alerts/frontend/views/`                                             |
