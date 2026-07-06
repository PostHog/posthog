import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { createFuse } from 'lib/utils/fuseSearch'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { toolbarApi } from '~/toolbar/toolbarApi'
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
                    const result = await toolbarApi.actions.list({
                        context: 'load_actions',
                        reauthenticateOnForbidden: true,
                    })
                    breakpoint()

                    if (!result.ok || !Array.isArray(result.data.results)) {
                        return values.allActions
                    }
                    return result.data.results
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
                    ? createFuse(allActions, {
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
