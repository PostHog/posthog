import type { ActivityLogItem } from './humanizeActivity'

// Matches WORKLOAD_TRIGGER_JOB_TYPE in posthog/models/activity_logging/activity_log.py.
const WORKLOAD_TRIGGER_JOB_TYPE = 'workload'

export interface WorkloadAttribution {
    providerName: string
    /** How the provider names the workload, for example "acme/web · deploy.yml run 1234". */
    actorLabel: string | null
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

/** The workload that made the change, when the row was written with a workload access token. */
export function parseWorkloadAttribution(logItem: Pick<ActivityLogItem, 'detail'>): WorkloadAttribution | null {
    const trigger = logItem.detail?.trigger
    if (trigger?.job_type !== WORKLOAD_TRIGGER_JOB_TYPE) {
        return null
    }
    const payload = (trigger.payload ?? {}) as Record<string, unknown>
    const repository = stringField(payload, 'repository')
    if (!repository) {
        return null
    }
    const runUrl = stringField(payload, 'run_url')
    return {
        providerName: stringField(payload, 'provider_name') ?? stringField(payload, 'provider') ?? 'Workload',
        actorLabel: stringField(payload, 'actor_label'),
        repository,
        workflow: stringField(payload, 'workflow'),
        runId: stringField(payload, 'run_id'),
        // Only an https link is rendered, so a stored value can never become a script URL.
        runUrl: runUrl?.startsWith('https://') ? runUrl : null,
        policyName: stringField(payload, 'policy_name'),
    }
}

/** For example "GitHub Actions · acme/web · deploy.yml run 1234". */
export function workloadActorLabel(attribution: WorkloadAttribution): string {
    if (attribution.actorLabel) {
        return `${attribution.providerName} · ${attribution.actorLabel}`
    }
    const run = [attribution.workflow, attribution.runId ? `run ${attribution.runId}` : null].filter(Boolean).join(' ')
    return [attribution.providerName, attribution.repository, run].filter(Boolean).join(' · ')
}
