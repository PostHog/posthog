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
| `iteration_budget`                    | The model's total experiment budget across all training runs. Default 50. Each scheduled retrain takes at most 10 from what remains, and a run started by hand can set its own budget.                               |
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

## Name it as a question

Use the question as the name: "Who will invite a teammate in the next 7 days?".
The UI already shows models as questions, and the name is what people see on every card.
