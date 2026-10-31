# Reading model quality

Quality has two stages. The model makes a promise at training time (holdout) and keeps it, or not, in production (realized).
Lead with the realized numbers when they exist, and say plainly when they do not exist yet.

## Where the numbers live

| Tool                                               | What it gives                                                                                                                                                                                                                           |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `posthog:autoresearch-retrieve`                    | The champion's `champion_holdout_auc`, `champion_realized_auc`, `champion_lift_at_10`, `champion_is_preliminary`, `champion_realized_auc_trend`, `people_scored`, `likely_count`, `first_check_expected_at` and `coverage`. Start here. |
| `posthog:autoresearch-online-performance-retrieve` | One row per model per validated date: realized AUC with a 95% interval, Brier score, calibration error and bins, mean prediction against base rate, lift at 10% and 20%.                                                                |
| `posthog:autoresearch-models-list`                 | Every champion, challenger and archived model with its scores. Use it to see whether a retrain promoted a new champion.                                                                                                                 |
| `posthog:autoresearch-models-retrieve`             | One model's recipe (feature SQL, transforms, model class) and its feature importances.                                                                                                                                                  |
| `posthog:autoresearch-training-runs-history`       | Each run's distilled summary: what won, what was tried and dropped.                                                                                                                                                                     |

## The quality label

The UI gives each champion a label from AUC, and states its basis:

| Label  | AUC        |
| ------ | ---------- |
| Strong | 0.8 and up |
| Fair   | 0.7 to 0.8 |
| Weak   | below 0.7  |

- The basis is **confirmed** when the champion has realized AUC and `champion_is_preliminary` is false. Otherwise it is **testing only** and comes from holdout AUC.
- A new champion has no realized rows until its first horizon has passed. `first_check_expected_at` says when the first check is due.
- AUC 0.5 is a coin flip. Above about 0.97 on holdout is suspicious: check that the features do not read the target or something that happens because of it.

## When realized AUC is missing after the horizon

A validated date where every scored person had the same outcome has no AUC.
Its online performance row carries the warning `single_class_no_auc`.
This is common on a rare target with a short horizon.
Tell the user that realized AUC needs dates where some people did the target and some did not, and that more dates will fill it in.

## When holdout and realized disagree

- **Realized a little below holdout** is normal. A gap of a few hundredths is noise, especially on days with few positives. The interval on each row shows how wide the noise is.
- **Realized far below holdout, consistently** suggests the training data does not look like today's population. Common causes: the inference population differs from the training population, behavior shifted, or the features leaked the outcome during training.
- **One bad day** with a wide interval is not a finding. Look at the trend over 7 or more dates before you draw a conclusion.

## Calibration

AUC measures ranking. Calibration measures whether a 30% score means 30% of those people do the target.

- Compare `mean_p_y` with `base_rate` on each realized row. If `mean_p_y` is clearly above, the model over-predicts. If it is clearly below, it under-predicts.
- On a rare target, training can sample down the negatives. Scoring corrects for that: `$autoresearch_p_y` is the corrected probability, and `$autoresearch_p_y_raw` keeps the model's own score. If calibration is still poor, tell the user to rely on the order and the segments, not on the absolute number.
- The Brier score and calibration error are lower-is-better. Compare them across dates of the same model, not across models with different base rates.

## Lift

Lift at 10% is the clearest sentence for a non-technical reader: "people in the top 10% are 3× more likely than average to do X".
Lift at 20% helps when the user plans to act on a larger group.

## Likelihood segments

The Predictions tab splits scored people into **Likely**, **Possible** and **Unlikely**.

- Once a model has enough realized history, the cut points come from lift over the realized base rate, and the cards read like "2× average or higher".
- Before that, a fixed pair of probability cut points is used.
- A saved cohort keeps the cut point it was created with, so its name states the probability range. Recreate a cohort if the segments move a lot.

## Coverage and freshness

Large populations score in rolling batches, so "scored today" and "everyone has a fresh score" are different claims.

- `coverage` on `posthog:autoresearch-retrieve` has `population`, `with_score`, `never_scored` and the score age in days (average, median, 90th percentile, oldest).
- `never_scored` above zero, or a median score age above the cadence, means a rolling population.
- When the user plans to target by score, check coverage first. A cohort built from the property only includes people who were scored.

## A short report

When the user asks "is my model any good?", answer in this order:

1. The question in plain words, and the label with its basis ("Fair, confirmed by real outcomes").
2. Lift at 10% as one sentence.
3. The realized trend: stable, improving or drifting, with the number of dates it rests on.
4. Anything that limits trust: few positives, poor calibration, low coverage, a champion too new to check.
5. One next step: wait for more dates, act on the Likely segment, or steer the next training run.
