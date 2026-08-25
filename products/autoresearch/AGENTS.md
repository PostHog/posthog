# Autoresearch

Agent-driven predictive modeling.
A user names a **target event**, a **population**, and a **horizon** ("who will download a file in the next 30 days?").
An agent then searches for the best model for that question, and once it finds one, the product scores the population on a cadence and writes the result back into PostHog as `autoresearch_prediction` events.

The framing is Karpathy's `autoresearch` prompt pattern: an agent edits one thing, runs a fixed eval, keeps the change if a single metric improved, reverts otherwise, and loops until a stop rule fires.
Here the "one thing" is a feature set plus a model spec, the fixed eval is holdout AUC on a labeled training population, and the loop runs inside a Tasks sandbox.

This directory holds the data model, the access gate, and the backend packages that have landed so far; each package has its own `AGENTS.md`.
The training loop, inference, evaluation, the API, the MCP tools, and the frontend land in later pieces of the split tracked in [#88464](https://github.com/PostHog/posthog/pull/88464).

## Data model in one pass

```text
AutoresearchPipeline          the standing question (target, population, horizon, cadence)
 ├─ AutoresearchTrainingRun   one attempt to find a better model
 │   └─ AutoresearchIteration one experiment inside that attempt (kept / discarded)
 ├─ AutoresearchModel         a trained model, role = champion | challenger | archived
 ├─ AutoresearchRun           one execution of inference or validation
 └─ AutoresearchSuggestion    a human- or agent-authored hypothesis for the next run to explore
```

`AutoresearchModel.artifact_prefix` points at the model's artifact bundle in object storage.
When it is empty the model carries only `model_recipe`, which the in-process scoring path reads.

Every model carries its own `team` foreign key and sits on `TeamScopedRootMixin`, so reads outside a team scope raise rather than crossing tenants.
Read through `Model.objects.for_team(team_id)` or inside a `team_scope(team_id)` block.
The five pipeline-owned models inherit `PipelineScopedModel`, whose `save()` fills `team` from the parent pipeline, so a create only has to pass `pipeline`.

## Feature flag and access

Gated by the `autoresearch` feature flag (`backend/access.py`).
Rollout is configured on the flag, and code only asks whether it is on.

The real-agent training path additionally needs Tasks access, because it runs in a Tasks sandbox.

## Invariants that cross package boundaries

These are the ones that have actually broken things.

- **Everything is keyed on `person_id`, one row per person.**
  Agent-authored `feature_sql` must be a read-only `SELECT` keyed on `person_id`, and the label and population queries key on it too.
  A mismatch here does not raise, it silently produces all-zero labels and a degenerate model.
  **A uniform score distribution is an identifier mismatch until proven otherwise, not a bad model.**
- **The agent proposes, the backend disposes.**
  Iterations are recorded by the agent, but champion selection happens server-side.
  Never let agent output pick the champion directly.
- **Autoresearch trains on identified users only.**
  On demo-style datasets that are largely anonymous, raw event counts wildly overstate how much training data exists.
