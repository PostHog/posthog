import { ApiConfig } from 'lib/api'

import { CyclotronJobInvocationGlobals, HogFunctionConfigurationContextId } from '~/types'

import { errorTrackingIssuesList } from 'products/error_tracking/frontend/generated/api'

export type SampleGlobalsLoader = (
    exampleGlobals: CyclotronJobInvocationGlobals
) => Promise<CyclotronJobInvocationGlobals>

/**
 * Per-context overrides for the "load sample globals" flow in the hog function test panel.
 * Contexts without an entry load the last event matching the configured filters.
 */
export const SAMPLE_GLOBALS_CONTEXTS: Partial<Record<HogFunctionConfigurationContextId, SampleGlobalsLoader>> = {
    'error-tracking': async (exampleGlobals) => {
        const response = await errorTrackingIssuesList(String(ApiConfig.getCurrentProjectId()), { limit: 20 })
        const issue = response.results[Math.floor(Math.random() * response.results.length)]
        if (!issue) {
            return exampleGlobals
        }
        return {
            ...exampleGlobals,
            event: {
                ...exampleGlobals.event,
                // Real issue lifecycle events use the issue id as the distinct_id
                distinct_id: issue.id,
                properties: {
                    name: issue.name ?? 'Unnamed issue',
                    description: issue.description ?? '',
                    status: issue.status,
                },
            },
        }
    },
}
