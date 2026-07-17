# Replay Vision: config-generic improvement suggestions and versioning

Date: 2026-07-17
Status: Design approved, pending spec review
Owner: team-replay
Feature flag: `replay-vision-quality` (existing, internal-only)

## Summary

The Quality tab currently runs one improvement loop, and it only works on the scanner's `prompt` string.
Users rate observations with a thumbs up or down plus optional free-text feedback, and the system proposes a rewritten prompt, versions it, and lets the user test it before applying.

This project generalizes that loop to the whole `scanner_config` for all four scanner types (monitor, classifier, scorer, summarizer).
The signal stays the same as today (thumbs rating plus feedback plus the AI-summarized feedback themes).
What changes is that a suggestion can now propose type-appropriate config edits alongside the prompt rewrite (new tags for a classifier, a scale tweak for a scorer, a length change for a summarizer), and version history reflects the full config rather than the prompt alone.

## Goals

- One improvement loop that works for every scanner type, driven by the labels users already leave.
- Each type proposes the config edits that make sense for it (see the per-type table below).
- Version history and the ratings-over-time view reflect the full `scanner_config`, not just the prompt.
- Fold the orphaned `suggest_tags` grounding into the classifier proposer so labeled sessions finally feed tag proposals.
- No regression for the existing monitor prompt flow. Existing suggestions keep rendering.

## Non-goals (deferred)

- Structured per-type corrections (a user recording the exact correct tags, score, or verdict).
  The signal stays thumbs plus free text this round.
  The data model is shaped so corrections can be added later without rework.
- Pass or fail evaluation for scorer and summarizer.
  Those types get a preview re-run only, because pass or fail needs ground truth we are deferring.
- Any change to the standalone editor-time `suggest_tags` endpoint. It stays for cold start.

## Background: current state (grounded in code)

- Versioning is already type-agnostic.
  `ReplayScanner.save()` bumps `scanner_version` on any change to `scanner_config` (and to model, query, sampling, provider, emits_signals), and every observation snapshots the full config via `scanner_snapshot`.
  Per-version rating stats read from that snapshot.
  See `products/replay_vision/backend/models/replay_scanner.py` and `temporal/types.py`.
- Suggestions are locked to the prompt.
  The LLM output schema (`_LlmPromptSuggestion`), the persisted model (`ReplayScannerPromptSuggestion.suggested_prompt` / `base_prompt`), the apply step (`config["prompt"] = ...`), and all UI copy assume one prose field.
  The generation pipeline itself already reads generically (rated sessions, feedback, themes, per-version trends). It just emits a prompt only.
  See `backend/prompt_suggestions.py` and `backend/api/prompt_suggestions.py`.
- Labels are thumbs only.
  `ReplayObservationLabel` holds `is_correct` plus free-text `feedback`, one team-shared label per observation.
  There is no structured correction field.
  See `backend/models/replay_observation_label.py` and `backend/api/observations.py`.
- `suggest_tags` is a separate island.
  It proposes classifier tags grounded in emitted tags, product taxonomy, and sibling vocabularies, and it ignores user labels and does not flow through the suggestion, apply, or versioning path.
  See `backend/tag_suggestions.py`.
- Evaluation is monitor and classifier only, comparing one discrete before or after outcome per session.
  Scorer (numeric) and summarizer (text) are excluded.
  See `backend/prompt_evaluation.py`.

## Decisions

- Signal model: feedback-driven and phased.
  Keep `is_correct` plus `feedback`.
  The LLM infers config edits from the labeled sessions, the feedback text, and the feedback themes.
  Design the suggestion schema config-generic so structured corrections can slot in later.
- Architecture: a generic core plus a per-type proposer registry (option B from brainstorming).

## Architecture

A thin type-agnostic core, with all type-specific knowledge behind one interface.

Generic core (unchanged responsibilities, generalized data):

- `ScannerConfigSuggestion` model: persist `base_config`, `suggested_config`, `changes[]`, rationale, status, and the `scanner_version` the suggestion was generated against.
- Generation harness: read rated sessions, feedback, feedback themes, and per-version trends, and manage quota, transactions, and superseding of prior pending suggestions.
  This is the existing `generate_prompt_suggestion` machinery with the prompt-specific bits moved into the monitor proposer.
- `apply()`: validate the merged config and save the scanner. The save already bumps `scanner_version`.
- Quality-tab shell and a change-card renderer driven by `changes[]`.

Per-type proposer registry, one `ConfigProposer` per `ScannerType`:

- `output_schema()`: the LLM JSON schema for what this type may propose.
- `system_prompt()`: instructions and guardrails for this type.
- `grounding(scanner)`: extra context (for the classifier, the emitted tags, product taxonomy, and sibling vocab that `suggest_tags` uses today).
- `to_config_patch(llm_output, base_config)`: turn the model output into a `scanner_config` patch.
- `to_changes(base_config, suggested_config)`: the typed diff that drives the UI and the human summary.

Adding a scanner type later means adding one proposer and touching nothing else.
This mirrors how the codebase already isolates per-type logic (`ObservationCard`, `resolveOrderByKey`).

## Data model

Evolve `ReplayScannerPromptSuggestion` into a config-generic shape with an additive migration:

- Add `base_config` (JSONField), `suggested_config` (JSONField), and `changes` (JSONField list).
- Each entry in `changes`: `{ field, kind, op, before, after, rationale }` where `kind` is one of `prompt`, `tags`, `scale`, `length`, `flag`, and `op` is one of `set`, `add`, `remove`, `rename`.
- Keep `base_prompt` and `suggested_prompt` populated for prompt changes during the transition so existing rows and the current UI keep working.
  Remove them in the final phase once the frontend has migrated.
- `NO_CHANGE` detection generalizes from "prompt strings equal" to "suggested_config equals base_config".
- On read, when `base_config` or `suggested_config` is null (a row written before this change), derive them from the prompt fields so old rows render through the new path.

The classifier proposer absorbs the `suggest_tags` grounding helpers.
The standalone `suggest_tags` endpoint stays unchanged for cold start, where there are no labels yet.

## Per-type proposal surface

| Type       | Config it can change                                     | Signal it grounds in                                                                                         | Proposals                                                                                                                                                                                                                                          |
| ---------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Monitor    | `prompt`, `allow_inconclusive`                           | thumbs plus feedback themes                                                                                  | Prompt rewrite (exists). Toggle `allow_inconclusive` when feedback shows the scanner was forced yes or no on genuinely ambiguous sessions, or was overusing inconclusive.                                                                          |
| Classifier | `prompt`, `tags[]`, `allow_freeform_tags`, `multi_label` | thumbs plus feedback plus emitted tag distribution, recurring freeform tags, product taxonomy, sibling vocab | Tag vocabulary ops: add tags for recurring themes and freeform hits, remove never-emitted or wrong tags, rename ambiguous tags, merge near-duplicates. Prompt rewrite of tagging criteria. Optionally flip `allow_freeform_tags` or `multi_label`. |
| Scorer     | `prompt`, `scale{min,max,label}`                         | thumbs plus feedback ("should be higher or lower") plus score distribution                                   | Prompt rewrite to sharpen the rubric and add score anchors (the rubric lives in the prompt, since scale is only min, max, and label). Adjust scale bounds or set the label.                                                                        |
| Summarizer | `prompt`, `length`                                       | thumbs plus feedback (missing, wrong, too long) plus facet distribution                                      | Prompt rewrite to emphasize missing info or drop noise. Change `length`. Facet guidance via the prompt (for example, always capture friction points).                                                                                              |

## Evaluation

Replace the hard `evaluationSupported = monitor || classifier` gate with a per-type capability.

- Discrete outcome (monitor, classifier): keep the `fixed`, `regressed`, `kept`, `still_wrong` re-run, but re-run with the full `suggested_config`, not just the suggested prompt.
  This closes the current limitation where evaluation applies the prompt only.
- Preview re-run (scorer, summarizer): re-run the suggested config on rated sessions and show the new output next to the old one (numeric score delta for scorer, text for summarizer).
  No pass or fail, because that needs ground truth we deferred.

## Versioning and frontend history

The backend engine already versions the full config, so `apply()` needs no change beyond writing the merged config.
The work is on the frontend:

- Generalize `ObservationVersionMarkerApi` and the "Prompt versions" card in the Configuration tab to carry the full `scanner_config`, so version history shows a per-version config diff.
- The ratings-chart version badges link to the config diff rather than a prompt-only view.

## Frontend changes

- Rename `PromptRecommendationPanel` to `ConfigRecommendationPanel` and render `changes[]` as change cards: reuse the Monaco diff for `prompt` changes, tag add, remove, and rename chips for `tags`, before and after for `scale` and `length`, and a toggle for flags.
- The evaluation panel keeps the discrete table for monitor and classifier and gains a preview table for scorer and summarizer.
- Labeling stays thumbs plus feedback. No correction UI this phase.
- Copy moves from "prompt recommendation" to wording that fits any config change.

## Backwards compatibility (must not break)

This is a hard requirement. The following invariants must hold, and each must be verified, not assumed.

- The migration is additive only.
  No column is dropped or renamed in the framework phase.
  The `base_prompt` and `suggested_prompt` columns stay until the final cleanup phase.
- Existing suggestion rows (prompt-only) render through the new path.
  When `base_config` or `suggested_config` is null, derive them from the prompt fields on read.
- The public API shape is preserved by addition.
  New fields are added to the serializers.
  No existing field is removed or retyped while the frontend still reads it.
  Regenerate the OpenAPI types with `hogli build:openapi` and confirm no existing generated type loses a field.
- The monitor prompt flow keeps its current behavior.
  A monitor with only a prompt change produces the same applied result as today.
- The standalone `suggest_tags` endpoint is untouched.
- The feature stays behind the `replay-vision-quality` flag. Nothing new is exposed when the flag is off.
- Downstream consumers of labels and suggestions keep working: `prompt_evaluation.py`, `feedback_themes.py`, `observation_stats.py`, `evaluate_prompt_suggestion.py`, and the frontend generated types.
  Each is checked against the new fields before merge.
- Run the full backend and frontend test suites plus `hogli ci:preflight` before each phase merges.

## Code quality

- Match the surrounding style in each file. Follow the existing patterns rather than introducing new ones.
- Keep files small and single-purpose. Each proposer is its own module.
- Comments are minimal. Explain why, never what.
  Delete any comment that restates the code.
  Preserve existing comments unless the change makes them obsolete.
- Write Python as if mypy strict is on: annotate signatures, avoid `Any`, use `TYPE_CHECKING` for type-only imports.
- Frontend uses explicit return types and puts business logic in the kea logic file, not React hooks.

## Implementation sequencing (phased, classifier first)

Each phase is independently shippable behind the existing flag.

1. Framework plus monitor and classifier.
   Generic model and additive migration, the proposer interface, the harness refactor, the monitor proposer (prompt plus `allow_inconclusive`), the classifier proposer (folds in `suggest_tags` grounding), the generic change-card UI, full-config version history, and evaluation re-run using the full config.
2. Scorer. Scale change cards and the preview evaluation mode.
3. Summarizer. Length and facet guidance and the preview evaluation mode.
4. Cleanup. Drop the `base_prompt` and `suggested_prompt` compatibility shim once the UI is fully migrated.

## Testing strategy

- Per-proposer unit tests: `output_schema`, `to_config_patch`, `to_changes`, and `NO_CHANGE` detection.
- Apply merges the config and bumps `scanner_version` (generic path).
- Backwards compatibility: an old prompt-only suggestion row renders and applies through the new path.
- Evaluation: discrete outcome unchanged for monitor and classifier, preview mode for scorer and summarizer.
- Frontend: change-card rendering per `kind`, version-history config diff, and the per-type evaluation table variants.
- No new test duplicates an existing one. Prefer parameterized cases across scanner types.

## Edge-case decisions

- Vocabulary changes (rename, merge, remove) apply going forward only.
  Historical observations keep their snapshotted tags.
  This is consistent with the immutable snapshot model, where every observation already carries the exact config that produced it.
- Scale changes go through the existing config validation (min below max).
  This phase adds no extra guard for shrinking a scale below already-observed scores, since past observations keep their snapshotted scores and nothing downstream re-clamps them.
- Applying a suggestion is one config write and therefore one version bump, even when it bundles a prompt rewrite and other config edits together.
  This matches how a manual multi-field edit versions today.
