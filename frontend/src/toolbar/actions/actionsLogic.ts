import Fuse from 'fuse.js'
import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { ActionType } from '~/types'

import type { actionsLogicType } from './actionsLogicType'

export const actionsLogic = kea<actionsLogicType>([
    path(['toolbar', 'actions', 'actionsLogic']),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    loaders(({ values }) => ({
        allActions: [
            [] as ActionType[],
            {
                // oxlint-disable-next-line @typescript-eslint/no-unused-vars
                getActions: async (_ = null, breakpoint: () => void) => {
                    const response = await toolbarFetch('/api/projects/@current/actions/')
                    const results = await response.json()

                    if (response.status === 403) {
                        toolbarConfigLogic.actions.authenticate()
                        return []
                    }

                    breakpoint()

                    if (!Array.isArray(results?.results)) {
                        throw new Error('Error loading actions!')
                    }

                    return results.results
                },
                updateAction: ({ action }: { action: ActionType }) => {
                    return values.allActions.filter((r) => r.id !== action.id).concat([action])
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
        actionCount: [(s) => [s.allActions], (allActions) => allActions.length],
    }),
    permanentlyMount(),
])
