import { ApiConfig } from 'lib/api'

import { CyclotronJobInvocationGlobals, HogFunctionConfigurationContextId } from '~/types'

import {
    errorTrackingFingerprintsList,
    errorTrackingIssuesRetrieve,
} from 'products/error_tracking/frontend/generated/api'

export type SampleGlobalsLoader = (
    exampleGlobals: CyclotronJobInvocationGlobals
) => Promise<CyclotronJobInvocationGlobals>

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
}
