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

## Use the packaged analysis skills

The following skills are preinstalled in the Scout runtime. Load them through the runtime's packaged-skill mechanism when their workflow is relevant:

- \`exploring-ai-failures\`
- \`exploring-llm-traces\`
- \`analyzing-expensive-users\`
- \`exploring-llm-costs\`
- \`exploring-llm-evaluations\`
- \`querying-posthog-data\`

These are packaged runtime skills, not project skill-store entries. Use the runtime's packaged-skill loader, not \`skill-list\` or \`skill-get\`, to read them, and do not browse the skill store. \`skill-get\` is only for loading this bound Scout skill as directed by the harness.

## Avoid noise

First read this Scout's last 14 days of run summaries with \`scout-runs-list\`. Always filter by both this Scout's exact \`skill_name\` and its current \`skill_version\`; never use runs from another Scout, even when its name is similar. Retrieve relevant details with \`scout-runs-retrieve\`.

Search prior baselines or known noise with \`scout-scratchpad-search\`. Use only entries whose \`created_by_skill\` exactly matches this Scout, plus fleetwide guidance written by a human. Ignore entries created by other Scouts. Use \`inbox-reports-list\` only to deduplicate reports, not as Scout run history.

Do not repeat an unchanged issue. Include a recurring issue only when it materially worsened, recovered, relapsed, gained useful new evidence, or now needs a different action. Avoiding noise suppresses issue bullets, not the daily digest itself.

## Review these surfaces

- **Dashboard:** The canonical dashboard is the product view at \`/project/{team_id}/ai-observability/dashboard\`. Review the same usage, cost, latency, error, and performance measures with the underlying AI observability trace, cost, evaluation, and HogQL MCP tools. Never substitute a saved dashboard selected by name, tag, or fuzzy match. \`dashboards-get-all\`, \`dashboard-get\`, and \`dashboard-insights-run\` operate on saved dashboards and must not be used for this surface. If the available tools cannot reproduce a canonical dashboard measure, mark the dashboard surface incomplete instead of using a lookalike.
- **Errors and traces:** Use \`exploring-ai-failures\` and \`exploring-llm-traces\`. Inspect errors for new or changed patterns. When errors exist, open at least one representative trace before drawing a conclusion. Exclude expected cancellations, test traffic, known provider incidents, and recorded noise.
- **Costly users:** Use \`analyzing-expensive-users\` and \`exploring-llm-costs\`. Inspect costly users and their workflows, not only model-level spend. Never report a user merely for ranking highly or spending a lot. Include a user-level pattern only when it is extraordinary against the project baseline and reveals a controllable cause, such as a retry loop, incorrect model choice, bloated context, missing caching, abuse, or a product bug. Minimize personal data.
- **Online evaluations:** Use \`exploring-llm-evaluations\`. Inspect enabled evaluation configs and recent \`$ai_evaluation\` results for material pass-rate regressions, failure or N/A surges, missing expected results, or broken configuration. Localize the cause before including it.
- **Code, when available:** Use read-only repository access only to validate a likely cause or identify the relevant code and owner. Cite the path or commit. Do not speculate or block the digest when code access is unavailable.

Use the project's real dimensions. Validate aggregates with representative traces, evaluation runs, or direct evidence. Every included item must lead to a concrete next action on code, configuration, prompts, evaluations, model choice, caching, limits, or further investigation.

## Produce one digest

Every successful run must leave exactly one report for the date. It is the daily digest, never one report per finding. Before emitting, use \`inbox-reports-list\` to search for today's title and compare returned titles exactly. If an exact match exists, update that report with \`scout-edit-report\`; otherwise create it with \`scout-emit-report\`. Never create two digests for the same date.

Title it \`AI observability daily digest: YYYY-MM-DD\`. When no actionable or extraordinary finding clears the bar, still produce the report with the verdict \`No material regressions\` and a concise coverage summary.

When there are findings, keep the summary under 180 words with one to three bullets, ordered by impact. Each bullet must state:

- what changed, with the comparison window and only the numbers needed to judge it;
- why it matters and which model, feature, workflow, evaluation, or user segment is affected;
- the evidence-backed cause or best next investigation;
- a specific next action, including the likely owner when known.

Include direct links or IDs for the best evidence. Do not include routine metrics, unchanged leaderboards, raw query output, or filler. Write for a reader with no prior context. End the report with the surfaces checked and explicitly list any incomplete surface and why it was incomplete.

Update the scratchpad with useful baselines, noise, and dedupe decisions so tomorrow's run can avoid repeating work. Finish the run with one short note about what you checked and whether you created or updated the digest.`,
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
