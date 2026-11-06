---
name: signals-scout-ai-observability-error-patterns
description: >
  Finds new or growing AI failure modes, including silent quality failures, and validates each
  pattern against real traces.
scout-tags:
  - ai-observability
---

# AI observability error patterns

Find new, growing, or recurring AI failure modes in the most recent complete 24 hours. Compare them with the preceding 24 hours and the recent 7-day baseline.

The main signal is a recurring failure mode within one use case, validated by real traces and tied to a concrete next action. Raw error counts are pointers to investigate, not findings. Important AI failures can return HTTP 200 with no exception.

## Use the packaged analysis skills

Load these preinstalled skills through the runtime's packaged-skill mechanism when relevant:

- `exploring-ai-failures`
- `exploring-llm-traces`
- `exploring-llm-clusters`
- `exploring-llm-evaluations`
- `querying-posthog-data`

These are packaged runtime skills, not project skill-store entries. Do not use `skill-list` or `skill-get` to load them.

## Avoid duplicate work

Read this Scout's last 14 days of run summaries with `scout-runs-list`, filtered by its exact `skill_name` and current `skill_version`. Retrieve relevant details with `scout-runs-retrieve`.

Search the scratchpad and recent Inbox reports for the use case, failure mode, error, evaluation, cluster, and suspected cause. If a live report already covers the same pattern, add only materially new evidence with `scout-edit-report`. Skip it when the evidence and impact are unchanged.

## Find and read failures

Work on one use case at a time because different trace types fail differently.

1. Discover the project's trace taxonomy from properties that actually exist, such as feature, workflow, model, or span name.
2. Choose the use case with the clearest recent change or the stalest prior coverage.
3. Select traces using the signals that fit the data: explicit errors, tool failures, retries, evaluation failures, negative feedback, latency or token outliers, semantic clusters, or a stratified sample.
4. Open and read real traces. Queries choose what to read but do not establish a failure mode.
5. Identify the first thing that went wrong in each failing trace and group traces by that root failure instead of downstream symptoms.
6. Continue until the common modes stabilize, with a maximum of 25 traces in one run.
7. Quantify each mode against the full use-case population. Keep sample counts and population estimates separate.

Look for loud errors and silent failures such as ignored instructions, wrong answers, missing context, tool misuse, loops, malformed output, or incomplete work. Do not infer a silent failure from text matching alone.

Minimize personal data. Summarize the relevant behavior and cite trace IDs or links without copying sensitive prompt or response content.

Close without a report when no repeated, materially changed, or actionable failure mode clears the bar.

## Report only actionable patterns

A report-worthy failure must appear across independent traces or have clear systemic impact, be new or materially worse than baseline, be validated by representative traces, and lead to a concrete action.

Create one report per root failure, not per trace or error string. Create no more than two reports per run. Search the Inbox again before writing. Edit a matching live report instead of creating a duplicate.

Title a new report `AI error pattern: <specific mode>`. Include the affected use case and comparison window, how often it appeared, what failed first, why it matters, and the best next action. Include one to three representative trace links or IDs.

Do not report expected cancellations, test or synthetic evaluation traffic presented as production impact, known provider incidents covered elsewhere, one-off traces without systemic impact, or error aggregates that were not validated by reading traces.

Finish with a short run summary covering what you reviewed, what you reported or updated, and what you ruled out.
