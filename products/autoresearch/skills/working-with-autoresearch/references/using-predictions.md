# Using predictions

A scored model writes its output in two places. Pick the one that fits the job.

| Output                           | Holds                                                                               | Use it for                                                       |
| -------------------------------- | ----------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| The output person property       | The newest probability for each scored person who resolves to a current distinct ID | Cohorts, feature flag targeting, workflow audiences, breakdowns  |
| `autoresearch_prediction` events | One event per scored person per scoring run, with full history                      | Score history, comparisons across models, custom analysis in SQL |

Take the property name from `output_person_property` on `posthog:autoresearch-retrieve`.
A scored person whose identity cannot be resolved still gets an event, but no property. So a cohort on the property can hold fewer people than the run reports as scored.

## Event properties

| Property                                                    | Meaning                                                                                                                                 |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `$autoresearch_p_y`                                         | The probability that the person does the target within the horizon, corrected for any negative sampling in training.                    |
| `$autoresearch_pipeline_id`                                 | The model (pipeline) id. Always filter on it: a project can have several models.                                                        |
| `$autoresearch_model_id`                                    | The champion that produced the score. Changes when a retrain promotes a new one.                                                        |
| `$autoresearch_model_role`                                  | `champion`, or `shadow` for a challenger scored alongside it before any promotion. Shadow events set no property. Filter on `champion`. |
| `$autoresearch_prediction_date`                             | The date the score is for. The horizon starts here.                                                                                     |
| `$autoresearch_target_event` / `$autoresearch_horizon_days` | The question the score answers.                                                                                                         |
| `$autoresearch_person_id`                                   | The scored person. Use it as the person key: some prediction events have no person attached.                                            |

## Common queries

Confirm the event exists with `posthog:read-data-schema` first. It appears only after the first scoring run.

Both queries read the newest prediction date only, so a manual score and the daily run do not mix, and a model that scores every few days still returns rows.
On a large population that scores in rolling batches, the newest date holds only that day's batch.

Top people from the newest prediction date:

```sql
WITH latest AS (
    SELECT max(properties.$autoresearch_prediction_date) AS d
    FROM events
    WHERE event = 'autoresearch_prediction'
      AND properties.$autoresearch_pipeline_id = '<pipeline_id>'
      AND properties.$autoresearch_model_role = 'champion'
      AND timestamp > now() - INTERVAL 30 DAY
)
SELECT
    coalesce(nullIf(properties.$autoresearch_person_id, ''), distinct_id) AS person,
    argMax(toFloat(properties.$autoresearch_p_y), timestamp) AS p
FROM events
WHERE event = 'autoresearch_prediction'
  AND properties.$autoresearch_pipeline_id = '<pipeline_id>'
  AND properties.$autoresearch_model_role = 'champion'
  AND timestamp > now() - INTERVAL 30 DAY
  AND properties.$autoresearch_prediction_date = (SELECT d FROM latest)
GROUP BY person
ORDER BY p DESC
LIMIT 50
```

Score spread on the newest prediction date, one score per person:

```sql
WITH latest AS (
    SELECT max(properties.$autoresearch_prediction_date) AS d
    FROM events
    WHERE event = 'autoresearch_prediction'
      AND properties.$autoresearch_pipeline_id = '<pipeline_id>'
      AND properties.$autoresearch_model_role = 'champion'
      AND timestamp > now() - INTERVAL 30 DAY
)
SELECT
    count() AS people,
    min(p) AS min_p,
    quantiles(0.1, 0.5, 0.9, 0.99)(p) AS p10_p50_p90_p99,
    max(p) AS max_p
FROM (
    SELECT
        coalesce(nullIf(properties.$autoresearch_person_id, ''), distinct_id) AS person,
        argMax(toFloat(properties.$autoresearch_p_y), timestamp) AS p
    FROM events
    WHERE event = 'autoresearch_prediction'
      AND properties.$autoresearch_pipeline_id = '<pipeline_id>'
      AND properties.$autoresearch_model_role = 'champion'
      AND timestamp > now() - INTERVAL 30 DAY
      AND properties.$autoresearch_prediction_date = (SELECT d FROM latest)
    GROUP BY person
)
```

On a rare target, healthy scores sit close together near zero, so look at the quantiles rather than equal-width buckets.
Quantiles that are all the same value point to an identifier problem. See [troubleshooting-and-steering.md](troubleshooting-and-steering.md).

## Acting on the scores

- **Cohort.** A dynamic cohort on the output property, for example `<output property> >= 0.6`. It updates as scores change.
- **Feature flag.** Target the flag with the same person property condition to show something only to the Likely group.
- **Workflow.** A batch workflow with the property as its audience filter, for example an email to people at risk of going inactive (low activity score).
- **Insight.** Break down the target event by the output property to show that higher scores really do the target more often.

The model page has shortcuts for these on the Predictions tab. They build the same filters.

Points worth telling the user:

- For `at_risk_of_inactivity`, the at-risk group is a **low** score, because the model predicts activity.
- Pick a threshold from the segments or the score spread, not a round number. On a rare target, 0.6 can match almost nobody.
- People who were never scored have no property value. A filter like `< 0.2` leaves them out, which is usually right, but check coverage on a large population.
- To measure the impact of acting on a score, hold back a random part of the targeted group. The prediction says who is likely; only a holdout shows that the action changed anything.
