---
name: working-with-autoresearch
description: >
  Use PostHog Autoresearch, agent-driven predictive models: ask "who will do X in the next N days?",
  let an agent train a model, then score people daily into a person property and
  `autoresearch_prediction` events. Use when a user wants to predict churn, activity, return,
  feature adoption, conversion or any event or action per person; create or validate a model from a
  template; start training or score now; read model quality (holdout vs realized AUC, lift,
  calibration, likelihood segments, coverage); steer training with suggestions; act on predictions
  with cohorts, feature flags, workflows or SQL; or diagnose a model that fails to train, scores
  everyone the same, or stops scoring. Trigger on "autoresearch", "predictive model", "propensity
  score", "churn prediction", "likely to convert", "who will do X", "predicted_p_",
  "autoresearch_prediction", "realized AUC", "champion model".
---

# Working with autoresearch

Autoresearch answers one standing question per model: **who in a population will do a target within a horizon?**
For example, "which active users will open a report in the next 7 days?".

1. The user names a **target** (an event or a PostHog action), a **population** and a **horizon** in days.
2. A training agent runs in a PostHog sandbox. It writes feature SQL and a model, scores each experiment on a holdout set, keeps what improves holdout AUC and discards the rest.
3. The server picks the **champion** from the kept experiments. The agent proposes; the backend decides.
4. Every cadence (daily by default, at 02:00 UTC), the champion scores the inference population.
   Each scored person gets an `autoresearch_prediction` event with their probability.
   A person who resolves to a current distinct ID also gets the model's output person property, for example `predicted_p_adopt_insights_14d`.
5. When a prediction date's horizon has passed, online validation checks the scores against what really happened and records **realized AUC**.

In the PostHog UI the entity is a **model**. The API and tools call it a **pipeline**. Use "model" when you talk to people.

Autoresearch is behind the `autoresearch` feature flag.
Training runs in a cloud sandbox, so it also needs PostHog Desktop access.
If the `autoresearch-*` tools are missing, the project probably does not have access yet.

## Pick the job

| The user wants to           | Start with                                                                                                             | Reference                                                                     |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Create a model              | `posthog:autoresearch-resolve-template-create` or a custom definition, then `posthog:autoresearch-validate-create`     | [defining-a-question.md](references/defining-a-question.md)                   |
| Know if a model is any good | `posthog:autoresearch-retrieve`, then `posthog:autoresearch-online-performance-retrieve`                               | [reading-model-quality.md](references/reading-model-quality.md)               |
| Use the predictions         | The output person property, or `posthog:execute-sql` on `autoresearch_prediction`                                      | [using-predictions.md](references/using-predictions.md)                       |
| Fix or steer a model        | `posthog:autoresearch-training-runs-list`, `posthog:autoresearch-runs-list`, `posthog:autoresearch-suggestions-create` | [troubleshooting-and-steering.md](references/troubleshooting-and-steering.md) |
| See what models exist       | `posthog:autoresearch-list`                                                                                            | This page                                                                     |

## Create, train, score

The usual path is short. Each tool's description names its prerequisites and refusals, so read it with `info` before the first call.

1. **Resolve or define.** Templates cover the common questions (activity, inactivity risk, return after first use, feature adoption, repeat behavior). A custom definition works when none fits. See [defining-a-question.md](references/defining-a-question.md).
2. **Validate.** `posthog:autoresearch-validate-create` with the same target, horizon, lookback and populations you will create with. It returns the base rate, positive and negative counts and warnings. Fix anything that sets `can_proceed` to false, and tell the user about the non-blocking warnings.
3. **Create.** `posthog:autoresearch-create`. The new model is a `draft` until training starts.
4. **Train.** `posthog:autoresearch-train-create` starts an agent run that takes a while (often tens of minutes). It costs real sandbox and LLM time, so confirm with the user before you start one, and never start a second run while one is live. A 403 means either the call came from inside a sandbox (ask the user to click **Start training** on the model's page) or the user has no PostHog Desktop access (the page will refuse too). Read the error message to tell them apart.
5. **Wait.** Poll `posthog:autoresearch-training-runs-list` at a relaxed pace. While the first run is in progress the model is `bootstrapping`, and a missing champion is normal.
6. **Score.** After a champion is promoted, the next daily sweep scores the population. `posthog:autoresearch-score-create` scores today now; call it once, then poll `posthog:autoresearch-runs-list`. A second manual score for the same date can duplicate predictions.

Pause, resume and delete are in the model's menu in the UI only.
Pausing stops scoring and new training runs. A training run already in progress keeps running, and it can still promote a champion.

## Model status

| Status          | Meaning                                                                                                |
| --------------- | ------------------------------------------------------------------------------------------------------ |
| `draft`         | Defined, never trained.                                                                                |
| `bootstrapping` | The first training run is in progress. No champion yet.                                                |
| `running`       | A champion exists and scores on the cadence. Retraining can still happen.                              |
| `converged`     | Treated like `running`: the champion still scores and is still validated.                              |
| `paused`        | No scoring and no new training until someone resumes it in the UI. A run already in progress finishes. |

The training run's `iteration_count` and `best_holdout_score` are written only when the run completes.
A healthy run can show 0 iterations while its experiments are already recorded, so do not call a run stuck from the counter alone.

## How to talk about results

- **Holdout AUC** is the score on held-back training data. It says how well the model ranked people in the past. Treat it as a promise.
- **Realized AUC** is the score against real outcomes after the horizon passes. Treat it as the proof. It wins over holdout AUC whenever it exists.
- The UI labels quality **Strong** at AUC 0.8 and up, **Fair** at 0.7 and up, and **Weak** below that, and says whether the label comes from testing only or is confirmed by real outcomes. Use the same words so the agent and the UI agree.
- **Lift at 10%** is the plain-language headline: "the top 10% are 3.2× more likely to do X than average".
- The score is a probability, but on a rare target it is often best read as a ranking. Say so when the base rate is below a few percent.

[reading-model-quality.md](references/reading-model-quality.md) covers calibration, likelihood segments, coverage and what to say when the numbers disagree.

## Guardrails worth keeping in mind

- **Changing the question means a new model.** The fields a model was trained on (target, horizon, populations) are frozen once a model exists. Create a new model rather than editing one.
- **Autoresearch trains on identified users only.** Anonymous traffic does not count toward training data, so raw event volume can overstate what is available. Trust the validation counts.
- **Scores are keyed on the person.** A model whose scores are almost all the same value usually has an identifier problem, not a weak signal. See [troubleshooting-and-steering.md](references/troubleshooting-and-steering.md).
- **Read the output property name, do not guess it.** Take `output_person_property` from `posthog:autoresearch-retrieve`. A derived name includes the target and the horizon (`predicted_p_<target>_<horizon>d`), and templates use their own prefix, so two models on one target do not overwrite each other.
- **A model costs money to train and query to score.** A very large population scores in rolling batches (about 45,000 people per run), so not everyone gets a fresh score every day. Validation tells you how many runs a full rescore takes.

## Bring your own agent

An agent outside PostHog (on a laptop, for example) can train a model for an existing pipeline.
It opens a run with `posthog:autoresearch-training-runs-create`, records each experiment with `posthog:autoresearch-training-runs-iterations-create`, uploads its bundle with `posthog:autoresearch-training-runs-artifacts-upload-create`, and finishes with `posthog:autoresearch-training-runs-complete-create`.
It pulls training data with `posthog:execute-sql`, because `posthog:autoresearch-materialize-features` writes only into a PostHog sandbox.
Read `posthog:autoresearch-training-runs-history` first to reuse what earlier runs on the same target learned.
The iteration tool's description is the contract for valid feature SQL: read it in full before the first iteration.
