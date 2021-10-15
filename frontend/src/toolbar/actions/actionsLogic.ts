import { kea } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { encodeParams } from 'kea-router'
import { actionsLogicType } from './actionsLogicType'
import { ActionType } from '~/types'

export const actionsLogic = kea<actionsLogicType>({
    loaders: ({ values }) => ({
        allActions: [
            [] as ActionType[],
            {
                // eslint-disable-next-line
                getActions: async (_ = null, breakpoint: () => void) => {
                    const params = {
                        temporary_token: toolbarLogic.values.temporaryToken,
                    }
                    const url = `${toolbarLogic.values.apiURL}/api/action/${encodeParams(params, '?')}`
                    const response = await fetch(url)
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
            (s) => [s.allActions],
            (allActions) =>
                [...allActions].sort((a, b) =>
                    (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled')
                ) as ActionType[],
        ],
        actionCount: [(s) => [s.sortedActions], (sortedActions) => sortedActions.length],
    },
})
