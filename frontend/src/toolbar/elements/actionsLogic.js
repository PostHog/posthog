import { kea } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { encodeParams } from 'kea-router'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { stepMatchesHref } from '~/toolbar/elements/utils'

export const actionsLogic = kea({
    loaders: {
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
            },
        ],
    },

    selectors: {
        actionsForCurrentUrl: [
            selectors => [selectors.allActions, currentPageLogic.selectors.href],
            (allActions, href) => {
                if (allActions.length === 0) {
                    return []
                }

                const actionsWithSteps = allActions
                    .filter(a => a.steps && a.steps.length > 0 && a.steps.find(s => s.event === '$autocapture'))
                    .filter(a => a.steps.find(step => stepMatchesHref(step, href)))
                return actionsWithSteps
            },
        ],
    },
})
