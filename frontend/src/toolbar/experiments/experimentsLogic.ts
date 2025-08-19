import Fuse from 'fuse.js'
import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
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
                    const results = await response.json()

                    if (response.status === 403) {
                        toolbarConfigLogic.actions.authenticate()
                        return []
                    }

                    breakpoint()

                    if (!Array.isArray(results?.results)) {
                        throw new Error('Error loading experiments!')
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
                    ? new Fuse(allExperiments, {
                          threshold: 0.3,
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
