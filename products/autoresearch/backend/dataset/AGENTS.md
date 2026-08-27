# Dataset

What the prediction problem actually _is_: who is in the population, what counts as a positive example, and whether the question is answerable at all.

Nothing here trains or scores anything. It is the shared vocabulary that `../training/` and `../inference/` both compile against — which is the whole point. If the trainer and the scorer disagreed about what a row means, the resulting model would be quietly wrong rather than loudly broken.

## What lives here

- `labeling.py`
  The single source of truth for "what does a training example look like?", and the most load-bearing module in the product.

  A training example is a `(person, T0, label)` triple: pick an anchor time `T0` for a person, then `label = 1` if the target event fires in `[T0, T0 + horizon_days)`.
  `T0` is a **deterministic hash of `person_id`**, placed at a fixed fraction of the user's `[first_ts, cutoff_ts)` span, so it is stable across runs and spread across the full lookback rather than clustered at the most-recent feasible point — one row per person, sampled once in their history. A `hash % span` remainder would move every time `cutoff_ts` moved with `now()`.

  Three call sites share this module so they cannot drift: the wizard's live estimate (sampled), the trainer (full materialization with fold split), and inference (per-person cutoff = `now()`).
  That is why the training-side `labeled_anchors` CTE (inside `build_training_features_sql()`) and `build_inference_anchors_sql()` live here rather than next to their callers.

  Also here: `_compile_population_filters()` (property filters → HogQL; a cohort filter or an unknown operator raises rather than being skipped), `_build_population_kind_conditions()` (semantic population kinds → HogQL, see below), `build_target_condition()` (event or action target → predicate), `NUM_FOLDS = 5` with fold 0 as holdout, and `IDENTIFIED_USERS_ONLY`.

- `validation.py`
  Pre-flight viability. `validate_pipeline_definition()` answers "is there enough here to learn anything?" before a run is launched — `MIN_TRAINING_ROWS` (100), `MIN_POSITIVE_EXAMPLES` (20), `MIN_IDENTIFIED_FRACTION` (0.5).
  Returns a `ValidationResult` carrying `ValidationWarning`s rather than raising, because the API surfaces them as advice.
- `templates.py`
  Built-in starting points. A template resolves to the same pipeline config shape as a fully custom pipeline, so creation and validation behave identically either way — there is no separate template code path downstream.
  Population specs use a semantic format (`performed_event_within_days`, `person_first_seen_within_days`, `active_not_performed_target`, `ever_performed_event`, `ever_performed_target`) that is compiled to HogQL by `labeling.py`. The target-relative kinds compile against the pipeline's target predicate, so an action target is matched by its matcher and not by its display name.
  `resolve_activity_event()` picks the team's real activity event, preferring `$pageview` → `$screen` → `$autocapture`, because "active user" means different things on web and mobile.

## Mental model

A pipeline definition is declarative. This package is what turns it into SQL.

```text
pipeline (target, population, horizon, lookback)
   │
   ├─ build_training_features_sql  → labeled_anchors CTE: one T0 per person, hashed,
   │    └─ + labels + fold             spread over lookback — the trainer's labeled population
   │
   └─ build_inference_anchors_sql  → cutoff = now(), no labels, no folds
        └─ the scorer's population
```

The two branches differ only in cutoff and whether labels and folds are attached. Everything else — population filters, identified-user restriction, target predicate — is shared code, deliberately.

## Things that bite

- **`IDENTIFIED_USERS_ONLY` is on.** Autoresearch trains on identified users only, so raw event counts badly overstate available training data on anonymous-heavy datasets. A target with thousands of events can yield a few dozen usable rows.
- **Validation is advisory, not enforcing.** `autoresearch_train` does not call it. A target that fails on volume will still train — deliberately, so thin local datasets are workable, but it means "the run completed" does not mean "the data was sufficient."
- **Random `T0` is a modeling decision, not an implementation detail.** Spreading anchors across the lookback keeps the model from over-fitting to one moment in calendar time. Changing it to most-recent-feasible would change what every model in the product means.
- **Everything keys on `person_id`.** See `../inference/AGENTS.md` for what goes wrong when a caller keys on `distinct_id` instead — it fails silently.

## Where the rest of the system meets this package

- **Trainer** — `../training/` materializes the labeled population from `build_training_features_sql()`.
- **Scorer** — `../inference/` materializes the unlabeled population from `build_inference_features_sql()`.
- **API** — `../presentation/views/views.py` calls `validate_pipeline_definition()` for the pre-create check and `resolve_template()` for template-backed creation; `resolve_target()` lives in `../presentation/views/serializers.py` and pairs with `build_target_condition()`.
- **Command** — `autoresearch_validate` is the headless entry to `validation.py`.
- **Agent-authored SQL** — the agent's `feature_sql` is spliced against these anchors via `_substitute_anchors()`. The `{anchors}` placeholder is part of the agent's contract, so it is documented in the brief in `../training/runner.py`.

## When editing this flow

- **Any change to what a row means goes here and only here.** If you add a cutoff rule, a population kind, or a label variant next to a caller instead, the trainer and scorer will drift and the failure will be silent.
- Keep the training-side `labeled_anchors` CTE and `build_inference_anchors_sql()` symmetrical. They should differ in cutoff, labels, and folds — nothing else.
- New population kinds need the semantic spec in `templates.py`, the compiler branch in `_build_population_kind_conditions()` in `labeling.py` (both row mode and anchor mode), and the required-key rules in the `PopulationDefinitionField` validator in `../presentation/views/serializers.py`. `POPULATION_KINDS` in `labeling.py` is the shared registry; a kind missing its compiler branch is rejected at creation and raises at query time.
- Every population kind and every event-property filter is evaluated **per user at T0** during training (the `HAVING` clause of the labeled CTE) and **as of the cutoff** at inference; only person-property filters apply at the scan. Deciding training membership as of `now()` would admit users on activity after T0, including the outcome window, and excluding "ever performed the target" users with a plain row filter would delete exactly the users whose post-T0 adoption provides the positive labels.
- Fold 0 is the holdout everywhere. If you change `NUM_FOLDS` or the holdout fold, every recorded `holdout_score` in the database becomes incomparable to new ones.
- **If you change the anchor, label, or population contract, update this file to match.**
