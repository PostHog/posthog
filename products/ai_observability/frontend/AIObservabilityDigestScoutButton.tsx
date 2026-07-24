import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ScoutCreateButton } from 'scenes/inbox/components/config/scouts/ScoutCreateButton'
import type { ScoutCreateInitialValues } from 'scenes/inbox/logics/scoutCreateModalLogic'

const AI_OBSERVABILITY_DIGEST_SCOUT_NAME = 'signals-scout-ai-observability-daily-digest'

export function getAIObservabilityDigestScoutInitialValues(): ScoutCreateInitialValues {
    return {
        name: AI_OBSERVABILITY_DIGEST_SCOUT_NAME,
        description:
            'Creates a concise, low-noise daily digest from the AI observability dashboard, errors, costly users, and online evaluations.',
        body: `# AI observability daily digest

Create one concise, actionable AI observability digest for the previous complete 24 hours in the project's timezone. Compare it with the preceding 24 hours, the recent 7-day baseline, and the same weekday when traffic is seasonal. Never compare a complete period with a partial one.

## Avoid noise

First read this scout's last 14 days of run summaries with \`scout-runs-list\`, relevant details with \`scout-runs-retrieve\`, and prior baselines or known noise with \`scout-scratchpad-search\`. Use \`inbox-reports-list\` to check recent digest and issue reports.

Do not repeat an unchanged issue. Include a recurring issue only when it materially worsened, recovered, relapsed, gained useful new evidence, or now needs a different action. Past digests are context, not reports to edit.

## Review these surfaces

- **Dashboard:** Discover the current dashboard at run time with \`dashboards-get-all\`, filtering for the \`llm-analytics\` tag or the "AI observability default" name. Then use \`dashboard-get\` and \`dashboard-insights-run\`. Review its insights for material changes in usage, cost, latency, errors, or performance.
- **Errors:** Read \`posthog:exploring-ai-failures\` and \`posthog:exploring-llm-traces\`. Investigate new or changed error patterns and open representative traces. Exclude expected cancellations, test traffic, known provider incidents, and recorded noise.
- **Costly users:** Read \`posthog:analyzing-expensive-users\` and \`posthog:exploring-llm-costs\`. Never report a user merely for ranking highly or spending a lot. Include a user-level pattern only when it is extraordinary against the project baseline and reveals a controllable cause, such as a retry loop, incorrect model choice, bloated context, missing caching, abuse, or a product bug. Minimize personal data.
- **Online evaluations:** Read \`posthog:exploring-llm-evaluations\`. Inspect enabled evaluation configs and recent \`$ai_evaluation\` results for material pass-rate regressions, failure or N/A surges, missing expected results, or broken configuration. Localize the cause before including it.
- **Code, when available:** Use read-only repository access only to validate a likely cause or identify the relevant code and owner. Cite the path or commit. Do not speculate or block the digest when code access is unavailable.

Use the project's real dimensions. Validate aggregates with representative traces, evaluation runs, or direct evidence. Every included item must lead to a concrete next action on code, configuration, prompts, evaluations, model choice, caching, limits, or further investigation.

## Produce one digest

Create at most one report per run. It is the daily digest, never one report per finding. If no actionable or extraordinary finding clears the bar, create no report.

Title it \`AI observability daily digest: YYYY-MM-DD\`. Keep the summary under 180 words with one to three bullets, ordered by impact. Each bullet must state:

- what changed, with the comparison window and only the numbers needed to judge it;
- why it matters and which model, feature, workflow, evaluation, or user segment is affected;
- the evidence-backed cause or best next investigation;
- a specific next action, including the likely owner when known.

Include direct links or IDs for the best evidence. Do not include routine metrics, unchanged leaderboards, raw query output, or filler. Write for a reader with no prior context.

Update the scratchpad with useful baselines, noise, and dedupe decisions so tomorrow's run can avoid repeating work. Finish the run with one short note about what you checked and why you did or did not create the digest.`,
        config: {
            enabled: true,
            emit: true,
            run_interval_minutes: 1440,
            run_cron_schedule: '0 9 * * *',
        },
    }
}

export function AIObservabilityDigestScoutButton(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.AI_OBSERVABILITY_DAILY_DIGEST_SCOUT]) {
        return null
    }

    return (
        <ScoutCreateButton
            creationMode="manual"
            initialValues={getAIObservabilityDigestScoutInitialValues()}
            type="secondary"
            data-attr="create-ai-observability-digest-scout"
        >
            Create daily digest
        </ScoutCreateButton>
    )
}
