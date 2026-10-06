import { ApiConfig } from 'lib/api'

import {
    CyclotronJobFiltersType,
    CyclotronJobInvocationGlobals,
    HogFunctionConfigurationContextId,
    PropertyOperator,
} from '~/types'

import {
    errorTrackingFingerprintsList,
    errorTrackingIssuesRetrieve,
} from 'products/error_tracking/frontend/generated/api'

export type SampleGlobalsLoader = (
    exampleGlobals: CyclotronJobInvocationGlobals,
    filters?: CyclotronJobFiltersType | null
) => Promise<CyclotronJobInvocationGlobals>

// An alert scoped to some health check kinds skips an event of any other kind, so the sample
// takes a kind the filters accept. Only an exact-match filter names an accepted kind. Any other
// operator, such as "is not", names kinds the alert excludes.
function sampleHealthCheckKind(filters?: CyclotronJobFiltersType | null): string {
    const kindFilter = filters?.properties?.find(
        (property) =>
            'key' in property &&
            property.key === 'kind' &&
            'operator' in property &&
            property.operator === PropertyOperator.Exact
    )
    const value = kindFilter && 'value' in kindFilter ? kindFilter.value : null
    const kind = Array.isArray(value) ? value[0] : value
    return typeof kind === 'string' && kind ? kind : 'test'
}

/**
 * Per-context overrides for the "load sample globals" flow in the hog function test panel.
 * Contexts without an entry load the last event matching the configured filters.
 */
export const SAMPLE_GLOBALS_CONTEXTS: Partial<Record<HogFunctionConfigurationContextId, SampleGlobalsLoader>> = {
    'error-tracking': async (exampleGlobals) => {
        const projectId = String(ApiConfig.getCurrentProjectId())
        // The issues list API doesn't expose fingerprints, so start from a fingerprint
        // record (which alert templates rely on) and resolve its issue.
        const response = await errorTrackingFingerprintsList(projectId, { limit: 20 })
        const fingerprintRecord = response.results[Math.floor(Math.random() * response.results.length)]
        if (!fingerprintRecord) {
            return exampleGlobals
        }
        const issue = await errorTrackingIssuesRetrieve(projectId, fingerprintRecord.issue_id)
        const properties: Record<string, any> = {
            name: issue.name ?? 'Unnamed issue',
            description: 'PostHog test alert',
            status: issue.status,
            severity: issue.severity,
            fingerprint: fingerprintRecord.fingerprint,
        }
        if (issue.assignee) {
            // Real issue lifecycle events stringify the assignee as {"type":...,"id":...},
            // and omit the property entirely when the issue is unassigned
            properties.assignee = JSON.stringify({ type: issue.assignee.type, id: issue.assignee.id })
        }
        return {
            ...exampleGlobals,
            event: {
                ...exampleGlobals.event,
                // Real issue lifecycle events use the issue id as the distinct_id
                distinct_id: issue.id,
                properties,
            },
        }
    },
    // Health alert templates read only this envelope. An empty title or summary renders an empty
    // Slack block, and Slack rejects the whole message.
    'health-alerts': async (exampleGlobals, filters) => ({
        ...exampleGlobals,
        event: {
            ...exampleGlobals.event,
            properties: {
                kind: sampleHealthCheckKind(filters),
                severity: 'warning',
                issue_id: 'test-issue-id',
                title: 'Test health check',
                summary: 'This is a test alert from PostHog',
                link: '/health',
                remediation: null,
                payload: {},
            },
        },
    }),
}
