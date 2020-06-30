import { kea } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { encodeParams } from 'kea-router'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { stepMatchesHref } from '~/toolbar/utils'

export const actionsLogic = kea({
    loaders: ({ values }) => ({
        allActions: [
            [],
            {
                getActions: async (_, breakpoint) => {
                    const params = {
                        temporary_token: toolbarLogic.values.temporaryToken,
                    }
                    const url = `${toolbarLogic.values.apiURL}api/action/${encodeParams(params, '?')}`
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
                updateAction: ({ action }) => {
                    return values.allActions.filter(r => r.id !== action.id).concat([action])
                },
                deleteAction: ({ id }) => {
                    return values.allActions.filter(r => r.id !== id)
                },
            },
        ],
    }),

    selectors: {
        sortedActions: [
            s => [s.allActions],
            allActions => [...allActions].sort((a, b) => (a.name || 'Untitled').localeCompare(b.name || 'Untitled')),
        ],
        actionsForCurrentUrl: [
            s => [s.sortedActions, currentPageLogic.selectors.href],
            (sortedActions, href) => {
                if (sortedActions.length === 0) {
                    return []
                }

                const actionsWithSteps = sortedActions
                    .filter(a => a.steps && a.steps.length > 0 && a.steps.find(s => s.event === '$autocapture'))
                    .filter(a => a.steps.find(step => stepMatchesHref(step, href)))

                return actionsWithSteps
            },
        ],
        actionCount: [s => [s.actionsForCurrentUrl], actionsForCurrentUrl => actionsForCurrentUrl.length],
    },
})
