import { CyclotronJobInvocationGlobals, HogFunctionConfigurationContextId } from '~/types'

import { errorTrackingIssuesList } from 'products/error_tracking/frontend/generated/api'

export interface SampleGlobalsContextLoaderArgs {
    projectId: string
    exampleGlobals: CyclotronJobInvocationGlobals
}

export interface SampleGlobalsContextCopy {
    loadButtonLabel: string
    loadButtonTooltip: string
}

export interface SampleGlobalsContext extends SampleGlobalsContextCopy {
    /** Shown when `load` throws without a message of its own */
    fallbackErrorMessage: string
    /**
     * Load real product data to populate the test globals.
     * Throw with a user-facing message to fall back to the example globals.
     */
    load: (args: SampleGlobalsContextLoaderArgs) => Promise<CyclotronJobInvocationGlobals>
}

export const DEFAULT_SAMPLE_GLOBALS_COPY: SampleGlobalsContextCopy = {
    loadButtonLabel: 'Load new event',
    loadButtonTooltip: 'Find the last event matching filters, and use it to populate the globals below.',
}

const NO_ISSUES_MESSAGE = 'No issues found in this project. Showing example data instead.'

/**
 * Per-context overrides for the "load sample globals" flow in the hog function test panel.
 * Contexts without an entry load the last event matching the configured filters.
 */
export const SAMPLE_GLOBALS_CONTEXTS: Partial<Record<HogFunctionConfigurationContextId, SampleGlobalsContext>> = {
    'error-tracking': {
        loadButtonLabel: 'Load real issue',
        loadButtonTooltip: 'Load a recent issue from this project, and use it to populate the globals below.',
        fallbackErrorMessage: NO_ISSUES_MESSAGE,
        load: async ({ projectId, exampleGlobals }) => {
            const response = await errorTrackingIssuesList(projectId, { limit: 20 })
            const issues = response.results
            if (!issues.length) {
                throw new Error(NO_ISSUES_MESSAGE)
            }
            const issue = issues[Math.floor(Math.random() * issues.length)]
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
    },
}
