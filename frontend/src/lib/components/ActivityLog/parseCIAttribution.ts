import type { ActivityLogItem } from './humanizeActivity'

// Matches CI_TRIGGER_JOB_TYPE in posthog/models/activity_logging/activity_log.py.
const CI_TRIGGER_JOB_TYPE = 'ci'

export interface CIAttribution {
    providerName: string
    repository: string
    workflow: string | null
    runId: string | null
    runUrl: string | null
    policyName: string | null
}

function stringField(payload: Record<string, unknown>, key: string): string | null {
    const value = payload[key]
    return typeof value === 'string' && value ? value : null
}

/** The CI job that made the change, when the row was written with a CI access token. */
export function parseCIAttribution(logItem: Pick<ActivityLogItem, 'detail'>): CIAttribution | null {
    const trigger = logItem.detail?.trigger
    if (trigger?.job_type !== CI_TRIGGER_JOB_TYPE) {
        return null
    }
    const payload = (trigger.payload ?? {}) as Record<string, unknown>
    const repository = stringField(payload, 'repository')
    if (!repository) {
        return null
    }
    const runUrl = stringField(payload, 'run_url')
    return {
        providerName: stringField(payload, 'provider_name') ?? stringField(payload, 'provider') ?? 'CI',
        repository,
        workflow: stringField(payload, 'workflow'),
        runId: stringField(payload, 'run_id'),
        // Only an https link is rendered, so a stored value can never become a script URL.
        runUrl: runUrl?.startsWith('https://') ? runUrl : null,
        policyName: stringField(payload, 'policy_name'),
    }
}

/** For example "GitHub Actions · acme/web · deploy.yml run 1234". */
export function ciActorLabel(attribution: CIAttribution): string {
    const run = [attribution.workflow, attribution.runId ? `run ${attribution.runId}` : null].filter(Boolean).join(' ')
    return [attribution.providerName, attribution.repository, run].filter(Boolean).join(' · ')
}
