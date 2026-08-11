import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'
import type { ScoutCreateInitialValues } from 'products/signals/frontend/inbox/logics/scoutCreateModalLogic'
import { scoutTags } from 'products/signals/frontend/inbox/utils/scoutTags'

import { getAIObservabilityDigestScoutInitialValues } from '../AIObservabilityDigestScoutButton'

export const AI_OBSERVABILITY_SCOUT_TAG = 'ai-observability'

export interface AIObservabilityScoutTemplate {
    key: 'daily-digest' | 'costly-users' | 'error-patterns'
    title: string
    description: string
    schedule: string
    initialValues: ScoutCreateInitialValues
}

export const AI_OBSERVABILITY_SCOUT_TEMPLATES: AIObservabilityScoutTemplate[] = [
    {
        key: 'daily-digest',
        title: 'Daily digest',
        description: 'Summarize meaningful changes in AI usage, cost, errors, costly users, and evaluations.',
        schedule: 'Daily at 9:00 AM',
        initialValues: getAIObservabilityDigestScoutInitialValues(),
    },
    {
        key: 'costly-users',
        title: 'Costly or unusual users',
        description: 'Find unusual usage and very costly users, then trace the spend to a cause you can act on.',
        schedule: 'Daily at 9:00 AM',
        initialValues: {
            name: 'signals-scout-ai-observability-costly-users',
            description:
                'Finds extraordinary user-level AI spend or usage, validates the cause in traces, and reports only patterns with a controllable next action.',
            body: `# AI observability costly or unusual users

Find extraordinary user-level cost or usage patterns in the most recent complete 24 hours. Compare them with the preceding 24 hours, the recent 7-day baseline, and the same weekday when traffic is seasonal. Never compare a complete period with a partial one.

A user ranking highly by spend is not a finding. Look for a material departure in unit economics or behavior with a controllable cause, validated in real traces. High volume with normal cost per trace may be healthy usage.

## Use the packaged analysis skills

Load these preinstalled skills through the runtime's packaged-skill mechanism when relevant:

- \`analyzing-expensive-users\`
- \`exploring-llm-costs\`
- \`exploring-llm-traces\`
- \`querying-posthog-data\`

These are packaged runtime skills, not project skill-store entries. Do not use \`skill-list\` or \`skill-get\` to load them.

## Avoid duplicate work

Read this Scout's last 14 days of run summaries with \`scout-runs-list\`, filtered by its exact \`skill_name\` and current \`skill_version\`. Retrieve relevant details with \`scout-runs-retrieve\`.

Search the scratchpad and recent Inbox reports for the user, segment, workflow, and suspected cause. If a live report already covers the same pattern, add only materially new evidence with \`scout-edit-report\`. Skip unchanged issues. Never create a second report for an unchanged issue.

## Investigate a bounded set

1. Rank identified users by generated-call spend. Include both \`$ai_generation\` and \`$ai_embedding\` when calculating full cost totals. Exclude rows where \`distinct_id = properties.$ai_trace_id\` when treating \`distinct_id\` as a user.
2. Establish the population baseline for cost share, traces, cost per generation, tokens, cache behavior, errors, and retries.
3. Select at most three candidates whose behavior materially differs from both the population and their own baseline.
4. Break each candidate down by model, provider, span, workflow, feature, or another property that exists in the project. Use \`read-data-schema\` before grouping by custom dimensions.
5. Open representative traces before explaining the cause. Aggregates identify candidates. Traces establish whether the cause is a retry loop, context growth, output growth, model choice, missing caching, abuse, or a product bug.

Minimize personal data. Use the least identifying stable label available. Never include raw prompts, responses, or full person-property objects in a report.

Close without a report when the highest-spend users are consistent with expected volume and normal unit economics.

## Report only actionable patterns

A report-worthy finding must be extraordinary against a relevant baseline, material and recent, supported by representative traces, and actionable through code, prompts, model choice, caching, limits, configuration, or product behavior.

Group users with the same root cause into one report. Create no more than two reports per run. Search the Inbox again before writing. Edit a matching live report instead of creating a duplicate.

Title a new report \`Unusual AI spend: <segment and cause>\`. Include the comparison window, the minimum numbers needed to judge the change, the trace-backed cause or best next investigation, and one specific next action. Include direct trace links or IDs as evidence.

Do not report routine top spenders, expected launches or batch jobs, test traffic, one costly trace without a repeatable problem, or a known provider incident already covered elsewhere.

Finish with a short run summary covering what you checked, what you reported or updated, and what you ruled out.`,
            config: {
                enabled: true,
                emit: true,
                run_interval_minutes: 1440,
                run_cron_schedule: '0 9 * * *',
                tags: [AI_OBSERVABILITY_SCOUT_TAG],
            },
        },
    },
    {
        key: 'error-patterns',
        title: 'Error patterns',
        description: 'Read real traces to find recurring errors and silent AI failures worth fixing.',
        schedule: 'Daily at 9:00 AM',
        initialValues: {
            name: 'signals-scout-ai-observability-error-patterns',
            description:
                'Finds new or growing AI failure modes, including silent quality failures, and validates each pattern against real traces.',
            body: `# AI observability error patterns

Find new, growing, or recurring AI failure modes in the most recent complete 24 hours. Compare them with the preceding 24 hours and the recent 7-day baseline.

The main signal is a recurring failure mode within one use case, validated by real traces and tied to a concrete next action. Raw error counts are pointers to investigate, not findings. Important AI failures can return HTTP 200 with no exception.

## Use the packaged analysis skills

Load these preinstalled skills through the runtime's packaged-skill mechanism when relevant:

- \`exploring-ai-failures\`
- \`exploring-llm-traces\`
- \`exploring-llm-clusters\`
- \`exploring-llm-evaluations\`
- \`querying-posthog-data\`

These are packaged runtime skills, not project skill-store entries. Do not use \`skill-list\` or \`skill-get\` to load them.

## Avoid duplicate work

Read this Scout's last 14 days of run summaries with \`scout-runs-list\`, filtered by its exact \`skill_name\` and current \`skill_version\`. Retrieve relevant details with \`scout-runs-retrieve\`.

Search the scratchpad and recent Inbox reports for the use case, failure mode, error, evaluation, cluster, and suspected cause. If a live report already covers the same pattern, add only materially new evidence with \`scout-edit-report\`. Skip it when the evidence and impact are unchanged.

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

Title a new report \`AI error pattern: <specific mode>\`. Include the affected use case and comparison window, how often it appeared, what failed first, why it matters, and the best next action. Include one to three representative trace links or IDs.

Do not report expected cancellations, test or synthetic evaluation traffic presented as production impact, known provider incidents covered elsewhere, one-off traces without systemic impact, or error aggregates that were not validated by reading traces.

Finish with a short run summary covering what you reviewed, what you reported or updated, and what you ruled out.`,
            config: {
                enabled: true,
                emit: true,
                run_interval_minutes: 1440,
                run_cron_schedule: '0 9 * * *',
                tags: [AI_OBSERVABILITY_SCOUT_TAG],
            },
        },
    },
]

export function isAIObservabilityScout(config: SignalScoutConfigApi): boolean {
    return scoutTags(config).includes(AI_OBSERVABILITY_SCOUT_TAG)
}
