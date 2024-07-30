import Fuse from 'fuse.js'
import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { ActionType } from '~/types'

import type { experimentsLogicType } from './experimentsLogicType'

export const experimentsLogic = kea<experimentsLogicType>([
    path(['toolbar', 'experiments', 'experimentsLogic']),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    loaders(({ values }) => ({
        allActions: [
            [] as ActionType[],
            {
                // eslint-disable-next-line @typescript-eslint/no-unused-vars
                getActions: async (_ = null, breakpoint: () => void) => {
                    const response = await toolbarFetch('/api/projects/@current/experiments/')
                    const results = await response.json()

                    if (response.status === 403) {
                        toolbarConfigLogic.experiments.authenticate()
                        return []
                    }

                    breakpoint()

                    if (!Array.isArray(results?.results)) {
                        throw new Error('Error loading experiments!')
                    }

                    return results.results
                },
                updateAction: ({ experiment }: { experiment: ActionType }) => {
                    return values.allActions.filter((r) => r.id !== experiment.id).concat([experiment])
                },
                deleteAction: ({ id }: { id: number }) => {
                    return values.allActions.filter((r) => r.id !== id)
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
        sortedActions: [
            (s) => [s.allActions, s.searchTerm],
            (allActions, searchTerm) => {
                const filteredActions = searchTerm
                    ? new Fuse(allActions, {
                          threshold: 0.3,
                          keys: ['name'],
                      })
                          .search(searchTerm)
                          .map(({ item }) => item)
                    : allActions
                return [...filteredActions].sort((a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'))
            },
        ],
        experimentCount: [(s) => [s.allActions], (allActions) => allActions.length],
    }),
    permanentlyMount(),
])
