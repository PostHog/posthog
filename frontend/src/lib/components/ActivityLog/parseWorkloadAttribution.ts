import { isObject } from 'lib/utils/guards'

import type { ActivityLogItem } from './humanizeActivity'

// Matches WORKLOAD_TRIGGER_JOB_TYPE in posthog/models/activity_logging/activity_log.py.
const WORKLOAD_TRIGGER_JOB_TYPE = 'workload'

export interface WorkloadClaimValue {
    name: string
    /** What the provider calls the claim, for example "Branch or tag". */
    label: string
    value: string
}

export interface WorkloadAttribution {
    providerName: string
    /** How the provider names the workload, for example "acme/web · deploy.yml run 1234". */
    actorLabel: string | null
    subjectName: string
    /** The claims the provider records, in the order the backend wrote them. */
    claims: WorkloadClaimValue[]
    runUrl: string | null
    policyName: string | null
}

function stringField(payload: Record<string, unknown>, key: string): string | null {
    const value = payload[key]
    return typeof value === 'string' && value ? value : null
}

function stringMap(value: unknown): Record<string, string> {
    if (!isObject(value)) {
        return {}
    }
    return Object.fromEntries(
        Object.entries(value).filter(
            (entry): entry is [string, string] => typeof entry[1] === 'string' && entry[1] !== ''
        )
    )
}

/** The workload that made the change, when the row was written with a workload access token. */
export function parseWorkloadAttribution(logItem: Pick<ActivityLogItem, 'detail'>): WorkloadAttribution | null {
    const trigger = logItem.detail?.trigger
    if (trigger?.job_type !== WORKLOAD_TRIGGER_JOB_TYPE) {
        return null
    }
    const payload = (trigger.payload ?? {}) as Record<string, unknown>
    const subjectName = stringField(payload, 'subject_name')
    if (!subjectName) {
        return null
    }
    const labels = stringMap(payload.claim_labels)
    const runUrl = stringField(payload, 'run_url')
    return {
        providerName: stringField(payload, 'provider_name') ?? stringField(payload, 'provider') ?? 'Workload',
        actorLabel: stringField(payload, 'actor_label'),
        subjectName,
        claims: Object.entries(stringMap(payload.claims)).map(([name, value]) => ({
            name,
            label: labels[name] ?? name,
            value,
        })),
        // Only an https link is rendered, so a stored value can never become a script URL.
        runUrl: runUrl?.startsWith('https://') ? runUrl : null,
        policyName: stringField(payload, 'policy_name'),
    }
}

/** For example "GitHub Actions · acme/web · deploy.yml run 1234". */
export function workloadActorLabel(attribution: WorkloadAttribution): string {
    return `${attribution.providerName} · ${attribution.actorLabel ?? attribution.subjectName}`
}
