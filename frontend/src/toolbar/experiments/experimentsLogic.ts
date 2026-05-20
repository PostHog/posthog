import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { createFuse } from 'lib/utils/fuseSearch'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
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

                    // toolbarFetch stubs a 401 when there's no access token, and the real
                    // backend can return 401/403 when project access is lost. In either
                    // case bounce through the auth flow rather than surface a generic
                    // "Error loading experiments!" exception that strands the panel.
                    if (response.status === 401 || response.status === 403) {
                        toolbarConfigLogic.actions.authenticate()
                        return []
                    }

                    if (!response.ok) {
                        captureToolbarException(
                            new Error(`Failed to load experiments: HTTP ${response.status}`),
                            'experiments-load',
                            { status: response.status }
                        )
                        return []
                    }

                    const results = await response.json()

                    breakpoint()

                    if (!Array.isArray(results?.results)) {
                        const bodyShape = results === null ? 'null' : Array.isArray(results) ? 'array' : typeof results
                        throw new Error(
                            `Error loading experiments: unexpected body shape (status=${response.status}, type=${bodyShape})`
                        )
                    }

                    return results.results
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
