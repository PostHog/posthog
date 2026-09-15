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

## The number is confidence, not probability

The model reports how confident it is in the verdict it gave, whichever way that verdict went.
It is not calibrated, and it is not comparable with a statistical detector's score.

The shared anomaly score folds the verdict and the confidence into one number:
`confidence` when the verdict is an anomaly, and `1 - confidence` when it is not.
Storing the raw number instead would plot a confident all clear above the threshold, which reads as
a check that would have fired.

Because the fold is not reversible, the check also stores the verdict itself, and the history
classification reads that rather than the folded score.

## When a check fires

A live check fires only when the model names the latest point.
A confident anomaly verdict about older history records `latest_point_not_flagged` and does not
fire, because the alert is about what is happening now.

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

## Gating

One function, `llm_detector_access_error`, tests the rollout flag and AI data processing consent.
It runs in the API and the Max writer when either adds an enabled AI alert, in the simulate
endpoint, and inside the detector on every scheduled check.

The last of those is what makes the flag a real stop on spend.
Turning it off leaves the alerts enabled, and each check then records an error naming the cause
rather than making a call.

The rollout is checked for the principal the check runs as, which is the alert's creator, not
whoever last edited it.
Privacy mode redacts the prompt and the verdict in AI observability.

## When the model is unavailable

A check that cannot reach a verdict records an error.
It never returns "no anomaly", because an alert that silently stops firing looks healthier than one
that reports a problem.

- A transient failure raises a retryable error, and the retry policy decides.
- A permanent one, such as withdrawn consent or a missing creator, is not retried.
- The simulate endpoint maps both to HTTP 503.

## Previewing

Simulate runs the detector against an insight without creating an alert or a check.
For the AI type it is a charged call, so it is throttled per project at 10 a minute, 60 an hour and
200 a day, and it refuses breakdown insights before making any call.

The preview judges the whole window in one call, which is not the same shape as a live check.
A live check judges only whether the latest point is anomalous.

## Where the code lives

| Piece                                    | Path                                                                          |
| ---------------------------------------- | ----------------------------------------------------------------------------- |
| Detector, prompt, verdict, errors        | `posthog/tasks/alerts/detectors/llm/`                                         |
| Detection context                        | `posthog/tasks/alerts/detectors/base.py`                                      |
| Chart rendering and metric description   | `posthog/tasks/alerts/charts.py`, `posthog/tasks/alerts/metric_definition.py` |
| Evaluation wiring, breach text, simulate | `products/alerts/backend/evaluation/detector.py`                              |
| Cap, cadence rule, access check          | `products/alerts/backend/llm_detector_limits.py`                              |
| API                                      | `products/alerts/backend/presentation/views/alert.py`                         |
| Max tool writer                          | `products/alerts/backend/max_tools.py`                                        |
| Editor and history UI                    | `products/alerts/frontend/views/`                                             |
