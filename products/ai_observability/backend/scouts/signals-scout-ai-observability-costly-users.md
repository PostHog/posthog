---
name: signals-scout-ai-observability-costly-users
description: >
  Finds extraordinary user-level AI spend or usage, validates the cause in traces, and reports only
  patterns with a controllable next action.
scout-tags:
  - ai-observability
---

# AI observability costly or unusual users

Find extraordinary user-level cost or usage patterns in the most recent complete 24 hours. Compare them with the preceding 24 hours, the recent 7-day baseline, and the same weekday when traffic is seasonal. Never compare a complete period with a partial one.

A user ranking highly by spend is not a finding. Look for a material departure in unit economics or behavior with a controllable cause, validated in real traces. High volume with normal cost per trace may be healthy usage.

## Use the packaged analysis skills

Load these preinstalled skills through the runtime's packaged-skill mechanism when relevant:

- `analyzing-expensive-users`
- `exploring-llm-costs`
- `exploring-llm-traces`
- `querying-posthog-data`

These are packaged runtime skills, not project skill-store entries. Do not use `skill-list` or `skill-get` to load them.

## Avoid duplicate work

Read this Scout's last 14 days of run summaries with `scout-runs-list`, filtered by its exact `skill_name` and current `skill_version`. Retrieve relevant details with `scout-runs-retrieve`.

Search the scratchpad and recent Inbox reports for the user, segment, workflow, and suspected cause. If a live report already covers the same pattern, add only materially new evidence with `scout-edit-report`. Skip unchanged issues. Never create a second report for an unchanged issue.

## Investigate a bounded set

1. Rank identified users by generated-call spend. Include both `$ai_generation` and `$ai_embedding` when calculating full cost totals. Exclude rows where `distinct_id = properties.$ai_trace_id` when treating `distinct_id` as a user.
2. Establish the population baseline for cost share, traces, cost per generation, tokens, cache behavior, errors, and retries.
3. Select at most three candidates whose behavior materially differs from both the population and their own baseline.
4. Break each candidate down by model, provider, span, workflow, feature, or another property that exists in the project. Use `read-data-schema` before grouping by custom dimensions.
5. Open representative traces before explaining the cause. Aggregates identify candidates. Traces establish whether the cause is a retry loop, context growth, output growth, model choice, missing caching, abuse, or a product bug.

Minimize personal data. Use the least identifying stable label available. Never include raw prompts, responses, or full person-property objects in a report.

Close without a report when the highest-spend users are consistent with expected volume and normal unit economics.

## Report only actionable patterns

A report-worthy finding must be extraordinary against a relevant baseline, material and recent, supported by representative traces, and actionable through code, prompts, model choice, caching, limits, configuration, or product behavior.

Group users with the same root cause into one report. Create no more than two reports per run. Search the Inbox again before writing. Edit a matching live report instead of creating a duplicate.

Title a new report `Unusual AI spend: <segment and cause>`. Include the comparison window, the minimum numbers needed to judge the change, the trace-backed cause or best next investigation, and one specific next action. Include direct trace links or IDs as evidence.

Do not report routine top spenders, expected launches or batch jobs, test traffic, one costly trace without a repeatable problem, or a known provider incident already covered elsewhere.

Finish with a short run summary covering what you checked, what you reported or updated, and what you ruled out.
