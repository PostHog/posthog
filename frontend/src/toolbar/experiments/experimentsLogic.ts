import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { createFuse } from 'lib/utils/fuseSearch'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { WebExperiment } from '~/toolbar/types'

import type { experimentsLogicType } from './experimentsLogicType'

/** Short, PII-free description of an unexpected value's shape for error messages. */
function describeShape(value: unknown): string {
    if (value === null) {
        return 'null'
    }
    if (Array.isArray(value)) {
        return 'array'
    }
    return typeof value
}

export const experimentsLogic = kea<experimentsLogicType>([
    path(['toolbar', 'experiments', 'experimentsLogic']),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    loaders(({ values }) => ({
        allExperiments: [
            [] as WebExperiment[],
            {
                // oxlint-disable-next-line @typescript-eslint/no-unused-vars
                getExperiments: async (_ = null, breakpoint: () => void) => {
                    const url = '/api/projects/@current/web_experiments/'
                    const response = await toolbarFetch(url)

                    if (response.status === 403) {
                        toolbarConfigLogic.actions.authenticate()
                        return []
                    }

                    // toolbarFetch returns a stubbed 401 when there's no access token yet —
                    // the toolbar simply isn't authenticated, so show an empty list, not an error.
                    if (response.status === 401) {
                        return []
                    }

                    breakpoint()

                    // Transient server errors aren't actionable for the user — soft-fail to an
                    // empty list and let them retry rather than surfacing a scary error panel.
                    if (response.status >= 500) {
                        toolbarLogger.warn('experiments', 'Server error loading experiments, returning empty list', {
                            status: response.status,
                            url,
                        })
                        return []
                    }

                    if (!response.ok) {
                        throw new Error(`Failed to load experiments: HTTP ${response.status} from ${url}`)
                    }

                    let results: unknown
                    try {
                        results = await response.json()
                    } catch {
                        throw new Error(`Failed to load experiments: response from ${url} was not valid JSON`)
                    }

                    const resultsList = (results as { results?: unknown } | null)?.results
                    if (!Array.isArray(resultsList)) {
                        throw new Error(
                            `Failed to load experiments: expected an array at "results" from ${url}, got ${describeShape(
                                resultsList
                            )}`
                        )
                    }

                    return resultsList as WebExperiment[]
                },
                updateExperiment: ({ experiment }: { experiment: WebExperiment }) => {
                    return values.allExperiments.filter((r) => r.id !== experiment.id).concat([experiment])
                },
                deleteExperiment: ({ id }: { id: number }) => {
                    return values.allExperiments.filter((r) => r.id !== id)
                },
            },
        ],
    })),
    reducers({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    }),
    selectors({
        sortedExperiments: [
            (s) => [s.allExperiments, s.searchTerm],
            (allExperiments, searchTerm) => {
                const filteredExperiments = searchTerm
                    ? createFuse(allExperiments, {
                          keys: ['name'],
                      })
                          .search(searchTerm)
                          .map(({ item }) => item)
                    : allExperiments
                return [...filteredExperiments]
            },
        ],
        experimentCount: [(s) => [s.allExperiments], (allExperiments) => allExperiments.length],
    }),
    permanentlyMount(),
])
