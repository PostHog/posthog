# Using predictions

A scored model writes its output in two places. Pick the one that fits the job.

| Output                                                    | Holds                                                   | Use it for                                                       |
| --------------------------------------------------------- | ------------------------------------------------------- | ---------------------------------------------------------------- |
| Person property, for example `predicted_p_adopt_insights` | The newest probability for each scored person           | Cohorts, feature flag targeting, workflow audiences, breakdowns  |
| `autoresearch_prediction` events                          | One event per person per scoring run, with full history | Score history, comparisons across models, custom analysis in SQL |

The property name is the model's `output_person_property` (see `autoresearch-retrieve`).

## Event properties

| Property                                                    | Meaning                                                                                                                                                    |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$autoresearch_p_y`                                         | The probability that the person does the target within the horizon, corrected for any negative sampling in training.                                       |
| `$autoresearch_pipeline_id`                                 | The model (pipeline) id. Always filter on it: a project can have several models.                                                                           |
| `$autoresearch_model_id`                                    | The champion that produced the score. Changes when a retrain promotes a new one.                                                                           |
| `$autoresearch_model_role`                                  | `champion`, or `shadow` for a challenger scored alongside it before any promotion. Shadow events have no person and set no property. Filter on `champion`. |
| `$autoresearch_prediction_date`                             | The date the score is for. The horizon starts here.                                                                                                        |
| `$autoresearch_target_event` / `$autoresearch_horizon_days` | The question the score answers.                                                                                                                            |
| `$autoresearch_person_id`                                   | The scored person.                                                                                                                                         |

## Common queries

Confirm the event exists with `read-data-schema` first. It appears only after the first scoring run.

Top people from the newest scoring date:

```sql
SELECT
    person_id,
    argMax(properties.$autoresearch_p_y, timestamp) AS p
FROM events
WHERE event = 'autoresearch_prediction'
  AND properties.$autoresearch_pipeline_id = '<pipeline_id>'
  AND properties.$autoresearch_model_role = 'champion'
  AND timestamp > now() - INTERVAL 3 DAY
GROUP BY person_id
ORDER BY p DESC
LIMIT 50
```

Score distribution of the latest run, as a sanity check:

```sql
SELECT
    floor(toFloat(properties.$autoresearch_p_y) * 10) / 10 AS bucket,
    count() AS people
FROM events
WHERE event = 'autoresearch_prediction'
  AND properties.$autoresearch_pipeline_id = '<pipeline_id>'
  AND properties.$autoresearch_model_role = 'champion'
  AND timestamp > now() - INTERVAL 1 DAY
GROUP BY bucket
ORDER BY bucket
```

A distribution with almost every score in one bucket usually means an identifier problem. See [troubleshooting-and-steering.md](troubleshooting-and-steering.md).

## Acting on the scores

- **Cohort.** A dynamic cohort on the output property, for example `predicted_p_adopt_insights >= 0.6`. It updates as scores change.
- **Feature flag.** Target the flag with the same person property condition to show something only to the Likely group.
- **Workflow.** A batch workflow with the property as its audience filter, for example an email to people at risk of going inactive (low activity score).
- **Insight.** Break down the target event by the output property to show that higher scores really do the target more often.

The model page has shortcuts for these on the Predictions tab. They build the same filters.

Points worth telling the user:

- For `at_risk_of_inactivity`, the at-risk group is a **low** score, because the model predicts activity.
- Pick a threshold from the segments or the score distribution, not a round number. On a rare target, 0.6 can match almost nobody.
- People who were never scored have no property value. A filter like `< 0.2` leaves them out, which is usually right, but check coverage on a large population.
- To measure the impact of acting on a score, hold back a random part of the targeted group. The prediction says who is likely; only a holdout shows that the action changed anything.
