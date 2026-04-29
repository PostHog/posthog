import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { createFuse } from 'lib/utils/fuseSearch'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { captureToolbarException } from '~/toolbar/toolbarPosthogJS'
import { WebExperiment } from '~/toolbar/types'

import type { experimentsLogicType } from './experimentsLogicType'

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
                    const response = await toolbarFetch('/api/projects/@current/web_experiments/')

                    breakpoint()

                    if (response.status === 401 || response.status === 403) {
                        toolbarConfigLogic.actions.authenticate()
                        return []
                    }

                    if (!response.ok) {
                        toolbarLogger.warn('experiments', 'Failed to load experiments', {
                            status: response.status,
                        })
                        return []
                    }

                    let results: { results?: unknown } | null = null
                    try {
                        results = await response.json()
                    } catch (e) {
                        captureToolbarException(e, 'experiments_parse', { status: response.status })
                        toolbarLogger.warn('experiments', 'Failed to parse experiments response', {
                            status: response.status,
                        })
                        return []
                    }

                    if (!Array.isArray(results?.results)) {
                        toolbarLogger.warn('experiments', 'Experiments response missing results array', {
                            status: response.status,
                        })
                        return []
                    }

                    return results.results as WebExperiment[]
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
