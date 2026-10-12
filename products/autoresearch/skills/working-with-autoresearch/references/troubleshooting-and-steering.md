# Troubleshooting and steering

## First look

For any "something is wrong with my model" question, read these three, in this order:

1. `autoresearch-retrieve`: status, champion, last scored time, coverage.
2. `autoresearch-training-runs-list`: the newest training runs, their status, `iteration_count`, `best_holdout_score` and `error`.
3. `autoresearch-runs-list`: the newest scoring and validation runs, their status, `rows_scored` and `error`.

## Symptoms

| Symptom                                          | Likely cause                                                                             | What to do                                                                                                                                                                                                                                                                                             |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Training run shows 0 iterations but is `running` | Normal. Counters are written only when the run completes.                                | Wait. Check again later.                                                                                                                                                                                                                                                                               |
| Training run `failed` with 0 iterations          | Usually the environment, not the question: access, quota or a sandbox problem.           | Read `error`. Confirm the user has PostHog Desktop access. Retry once from the model page.                                                                                                                                                                                                             |
| `autoresearch-train-create` returns 403          | The call came from inside a sandbox.                                                     | Ask the user to start training from the model's page. Do not retry.                                                                                                                                                                                                                                    |
| `autoresearch-train-create` returns 400          | A run is already live, the model is paused, or its creator or target is no longer valid. | Wait for the live run, resume in the UI, or recreate the model.                                                                                                                                                                                                                                        |
| Training completed but no champion               | No experiment produced a usable model, or none beat the current champion.                | Read the run's summary with `autoresearch-training-runs-history`. Check the base rate and positive count.                                                                                                                                                                                              |
| Almost every score is the same value             | An identifier mismatch between the features and the people being scored.                 | Look at the champion's feature SQL with `autoresearch-models-retrieve`. Every row must be keyed on the person id. Report it as a product issue if the SQL looks right.                                                                                                                                 |
| Holdout AUC above about 0.97                     | The features likely see the outcome, or a proxy that happens because of it.              | Read the feature importances. If the top feature is the target or a step after it, suggest removing it.                                                                                                                                                                                                |
| Scoring run `failed`                             | The feature query was too heavy, or a transient error.                                   | Read `error`. After two scheduled days in a row of repeatable failures (a query limit, a query error, a model that will not load), the champion counts as unscorable and the product replaces it. A repeated memory error means the features scan too much: steer the next run toward shorter windows. |
| `rows_scored` far below the population           | Rolling batches on a large population.                                                   | Expected. Read coverage on `autoresearch-retrieve`.                                                                                                                                                                                                                                                    |
| No realized AUC yet                              | The horizon has not passed since the champion's first scoring.                           | Wait. `first_check_expected_at` on `autoresearch-retrieve` says when.                                                                                                                                                                                                                                  |
| Realized AUC drops over several dates            | Behavior shifted, or the training population no longer matches who is scored.            | Compare training and inference populations. Retrain, or steer with a suggestion.                                                                                                                                                                                                                       |

## Steering with suggestions

A suggestion is a note to the training agent. It reads queued suggestions at the start of the next training run.

- `autoresearch-suggestions-create` with a free-text `prompt`.
  Good suggestions name a hypothesis: "account for day-of-week, the target spikes on Mondays", "try features from the billing page events", "drop the recency feature, I suspect it leaks".
- `priority: "try_next"` makes the agent act on it before its own ideas. The default `consider` is advisory.
- After the next run, `autoresearch-suggestions-list` shows how the agent handled each one: `acted_on`, `picked_up` or `dismissed`, with a one-line `agent_response`.
- Suggestions do not start a run. Start one from the model page, or with `autoresearch-train-create` after the user confirms.

The agent decides whether a suggestion helps, and the server still picks the champion by score. A suggestion that makes the model worse is recorded and dropped.

## When to start over

Create a new model instead of retraining when:

- The target, horizon or population should change. These are frozen once a model exists.
- The validation counts were marginal and the realized AUC has stayed near 0.5 for many dates.
- The question no longer matches what the team acts on.

Leave the old model in place until the new one has realized results, then pause or archive the old one in the UI.
