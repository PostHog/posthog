# Defining a question

A model answers "who in **population** will do **target** within **horizon** days?".
Most of a model's value is decided here, before any training. A sharp question with enough positives beats a vague one with a clever model.

## Start from what the user will do with the answer

Ask what action follows the prediction before you pick a target:

- "Reach users before they go quiet" points to an inactivity question, scored on currently active users.
- "Nudge people toward feature X" points to adoption of X, scored on active users who have not used X yet.
- "Find who is ready for a sales touch" points to a conversion event, scored on the accounts sales can contact.

The population should be the people the user can act on. The horizon should match how fast they can act. A 1-day horizon is useless to a team that runs a weekly campaign.

## Templates

`posthog:autoresearch-resolve-template-create` turns a template key and optional overrides into a full config.

| Key                      | Question                                   | Target                  | Population                              | Default horizon |
| ------------------------ | ------------------------------------------ | ----------------------- | --------------------------------------- | --------------- |
| `likely_active_soon`     | Which active users will be active again?   | Resolved activity event | Did that event in the last 30 days      | 7 days          |
| `at_risk_of_inactivity`  | Which active users will not be active?     | Resolved activity event | Did that event in the last 60 days      | 14 days         |
| `return_after_first_use` | Which new users will come back?            | Resolved activity event | First seen in the last 14 days          | 7 days          |
| `feature_adoption`       | Who will use a feature for the first time? | User-supplied event     | Active in 30 days, never did the target | 14 days         |
| `repeat_key_behavior`    | Who will do a key action again?            | User-supplied event     | Did the target at least once            | 7 days          |

- The activity templates resolve the event from the project's schema. They prefer `$pageview`, then `$screen`, then `$autocapture`, then the custom event with the most identified users. Check `resolved_activity_event` against `activity_event_alternatives`, and re-resolve with a `target_event` override if a different event means "active" for this product.
- `at_risk_of_inactivity` still predicts the probability of **activity**. The at-risk group is people with a **low** score (for example below 0.2). Explain this to the user, because the name suggests the opposite.
- `feature_adoption` and `repeat_key_behavior` need `target_event`. Confirm the event exists with `posthog:read-data-schema` first.
- `repeat_key_behavior` suits a behavior that people do only sometimes. It is a weak question for a habit, such as a `report opened` event that most of the population does every week. See [the habit check](#sense-check-before-you-create).

Templates take an event target. For an action target, build a custom definition.

## Custom definitions

Pass the same fields to `posthog:autoresearch-validate-create` and `posthog:autoresearch-create`:

| Field                                 | Notes                                                                                                                                                                                                                |
| ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `target_event` or `target_definition` | An event name, or `{"type": "action", "action_id": N}` for an action (multi-step, property or autocapture matchers). With an action, `target_event` is only a label. An action target needs the `action:read` scope. |
| `horizon_days`                        | 1 to 365. Default 7.                                                                                                                                                                                                 |
| `training_lookback_days`              | 7 to 730. Default 180. Must be longer than the horizon. Longer gives more examples but includes older behavior.                                                                                                      |
| `training_population`                 | Who can be a training example. `{}` means all identified users.                                                                                                                                                      |
| `inference_population`                | Who gets scored. Defaults to the training population. Keep the two consistent unless there is a clear reason.                                                                                                        |
| `cadence_days`                        | Rescore every N days. Default 1.                                                                                                                                                                                     |
| `iterations_per_run`                  | The experiments in each training run, 1 to 50. Default 5. Scheduled runs and a run started by hand use it, and a run started by hand can override it.                                                                |
| `research_interval_days`              | How often scheduled research runs once the first burst ends: 7, 14, 30, 60 or 90 days, or null for only when asked. Default 7.                                                                                       |
| `iteration_budget`                    | Deprecated. Scheduled training no longer reads or spends it.                                                                                                                                                         |
| `output_person_property`              | Optional. Derived from the target and horizon when omitted.                                                                                                                                                          |

### Population shapes

A population is either a semantic kind or a list of person property filters:

```json
{ "kind": "performed_event_within_days", "event": "$pageview", "days": 30 }
{ "kind": "person_first_seen_within_days", "days": 14 }
{ "kind": "active_not_performed_target", "active_within_days": 30 }
{ "kind": "ever_performed_event", "event": "purchase" }
{ "kind": "ever_performed_target" }
{ "properties": [{ "key": "plan", "value": ["pro"], "operator": "exact", "type": "person" }] }
```

- "Ever" and "not performed" look back over the training lookback window, not all time.
- The target-relative kinds use the model's own target, so they follow an action's matcher.
- Every kind is evaluated at each training example's point in time, and at the scoring cutoff for inference. Person property filters use current values, so a filter on a property that changes often can leak the future into training.
- An unknown kind is rejected. An empty population means all identified users, which is rarely what the user meant on a large project.

## Read the validation result

`posthog:autoresearch-validate-create` is advisory: `posthog:autoresearch-create` does not block on it. Run it anyway and read every field.

Blocking errors (`can_proceed` is false):

| Code                           | What to do                                                                                                                                |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `low_volume`                   | Under 100 people. Widen the population or lengthen the lookback.                                                                          |
| `low_positives`                | Under 20 people did the target. Lengthen the horizon or the lookback, or pick a more common target.                                       |
| `low_negatives`                | Under 20 people did not do the target. Shorten the horizon, pick a rarer target, or use a population with more people who do not convert. |
| `horizon_exceeds_lookback`     | Raise `training_lookback_days` above `horizon_days`.                                                                                      |
| `population_too_large` (error) | Narrow the training population.                                                                                                           |

Warnings to pass on:

| Code                          | What it means for the user                                                                                                                    |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `extreme_imbalance`           | Base rate below 1%. The model can still rank well, but probabilities are small and noisy, and realized AUC needs many days of data to settle. |
| `near_universal`              | Above 95% do the target anyway. The model has little to add. Suggest a rarer target or a narrower population.                                 |
| `population_too_large` (info) | Scoring runs in rolling batches. The message says how many runs a full rescore takes.                                                         |

## Sense check before you create

Validation finds definitions that cannot train. It does not find definitions that train well and say little.
A weak question can still get a high holdout AUC, and each training run costs real money.
Run these checks on the definition and the validation result before you call `posthog:autoresearch-create`.

For each check that fires, tell the user what you found in one or two sentences, and propose a change.
The user decides. A finding never blocks a create that the user confirms.
The thresholds are guides, not limits.

| Check                               | It fires when                                                                                                                                             | What to propose                                                                                                                                         |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The populations differ              | `training_population` and `inference_population` are not the same                                                                                         | Use the same population for both. Or write the reason in one sentence and ask the user to confirm it.                                                   |
| The target is a habit               | The population comes from the target (`ever_performed_target`, or `performed_event_within_days` on the target event), or the base rate is above about 60% | Ask what the user will do with the answer. Offer the inverse question (who will stop), a rarer target, or a population of people who did not do it yet. |
| Too few positives for the holdout   | `positive_count` is below about 100                                                                                                                       | Tell the user that the holdout AUC will be noisy. Offer a longer horizon, a longer lookback or a wider population, then validate again.                 |
| A person property filter can change | A population filters on a property that changes over time, such as a plan or a status                                                                     | Tell the user that training reads today's value for past examples. Offer an event-based population.                                                     |
| The horizon does not fit the action | The horizon is shorter than the time the user needs to act, or much longer than the behavior takes                                                        | Offer a horizon that fits.                                                                                                                              |

Why each check matters:

- **The populations differ.** A feature can learn to tell the two groups apart. That feature scores well in training and adds little on the people who get scored. For example, a model trains on all identified users and scores only people with `plan = pro`.
- **The target is a habit.** When people who did the target recently will almost surely do it again, one recency or frequency feature ranks about as well as the full model. The holdout AUC is high, but the model only restates a rule the user already knows. The baseline query below measures this.
- **Too few positives for the holdout.** The holdout is one fold in five, split by person. 20 positives put about 4 people in the holdout, and 100 positives put about 20. With so few, one person more or less moves the AUC a lot.
- **A person property filter can change.** Person property filters use current values. A person who moved to `pro` last week is `pro` in examples from six months ago, so the population leaks the future into training.
- **The horizon does not fit the action.** A 1-day horizon does not help a team that runs a weekly campaign. A 90-day horizon on a weekly behavior makes almost everyone a positive.

### Measure a naive baseline

One `posthog:execute-sql` query shows how much a simple rule already explains.
It splits the population by whether people did the target in the `horizon_days` before a cutoff date. Then it counts how many in each group did the target in the `horizon_days` after the cutoff.
Replace each `{placeholder}`, and use a cutoff at least `horizon_days` in the past, so that the second window is complete.
This shape uses an event-based population. Change the `HAVING` clause to match the model's population.

```sql
SELECT
    did_before,
    count() AS people,
    countIf(did_after) AS did_after_people,
    round(did_after_people / people, 3) AS rate_after
FROM (
    SELECT
        person_id,
        countIf(event = '{target_event}'
            AND timestamp >= toDateTime('{cutoff}') - toIntervalDay({horizon_days})
            AND timestamp < toDateTime('{cutoff}')) > 0 AS did_before,
        countIf(event = '{target_event}'
            AND timestamp >= toDateTime('{cutoff}')
            AND timestamp < toDateTime('{cutoff}') + toIntervalDay({horizon_days})) > 0 AS did_after
    FROM events
    WHERE event IN ('{target_event}', '{population_event}')
      AND timestamp >= toDateTime('{cutoff}') - toIntervalDay(greatest({horizon_days}, {population_days}))
      AND timestamp < toDateTime('{cutoff}') + toIntervalDay({horizon_days})
    GROUP BY person_id
    HAVING countIf(event = '{population_event}'
        AND timestamp >= toDateTime('{cutoff}') - toIntervalDay({population_days})
        AND timestamp < toDateTime('{cutoff}')) > 0
)
GROUP BY did_before
ORDER BY did_before
```

Read the two rows:

- Compare `rate_after` in the `did_before = 1` row with `rate_after` in the `did_before = 0` row.
- When the first rate is several times the second, and most of the people who did the target are in the first row, a model on this question will mostly restate that rule.
- Tell the user this, and offer the proposals from the habit check.
- When the two rates are close, the rule explains little, and a model has room to add value.

## Name it as a question

Use the question as the name: "Who will invite a teammate in the next 7 days?".
The UI already shows models as questions, and the name is what people see on every card.
