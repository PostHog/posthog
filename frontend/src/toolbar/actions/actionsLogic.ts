import { kea } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import type { actionsLogicType } from './actionsLogicType'
import { ActionType } from '~/types'
import Fuse from 'fuse.js'
import { toolbarFetch } from '~/toolbar/utils'

export const actionsLogic = kea<actionsLogicType>({
    path: ['toolbar', 'actions', 'actionsLogic'],
    actions: {
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    },
    reducers: {
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    },
    loaders: ({ values }) => ({
        allActions: [
            [] as ActionType[],
            {
                // eslint-disable-next-line @typescript-eslint/no-unused-vars
                getActions: async (_ = null, breakpoint: () => void) => {
                    const response = await toolbarFetch('/api/projects/@current/actions/')
                    const results = await response.json()

                    if (response.status === 403) {
                        toolbarLogic.actions.authenticate()
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
    }),

    selectors: {
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
                return [...filteredActions].sort((a, b) =>
                    (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled')
                ) as ActionType[]
            },
        ],
        actionCount: [(s) => [s.allActions], (allActions) => allActions.length],
    },
})
