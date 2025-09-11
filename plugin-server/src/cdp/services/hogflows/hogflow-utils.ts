import { DateTime } from 'luxon'

import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { filterFunctionInstrumented } from '~/cdp/utils/hog-function-filtering'
import { HogFlow, HogFlowAction } from '~/schema/hogflow'

export const findActionById = (hogFlow: HogFlow, id: string): HogFlowAction => {
    const action = hogFlow.actions.find((action) => action.id === id)
    if (!action) {
        throw new Error(`Action ${id} not found`)
    }

    return action
}

export const findActionByType = <T extends HogFlowAction['type']>(
    hogFlow: HogFlow,
    type: T
): Extract<HogFlowAction, { type: T }> | undefined => {
    const action = hogFlow.actions.find((action) => action.type === type)
    if (!action) {
        return undefined
    }

    return action as Extract<HogFlowAction, { type: T }>
}

export const findNextAction = (hogFlow: HogFlow, currentActionId: string, edgeIndex?: number): HogFlowAction => {
    const edges = hogFlow.edges.filter((edge) => edge.from === currentActionId)

    let nextActionId: string | undefined

    if (edgeIndex === undefined) {
        nextActionId = edges.find((edge) => edge.type === 'continue')?.to
    } else {
        nextActionId = edges.find((edge) => edge.type === 'branch' && edge.index === edgeIndex)?.to
    }

    if (!nextActionId) {
        throw new Error(`No next action found for action ${currentActionId}`)
    }

    return findActionById(hogFlow, nextActionId)
}

export function ensureCurrentAction(invocation: CyclotronJobInvocationHogFlow): HogFlowAction {
    // If we don't have a current action then we need to set it to the trigger action
    if (!invocation.state.currentAction) {
        const triggerAction = invocation.hogFlow.actions.find((action) => action.type === 'trigger')
        if (!triggerAction) {
            throw new Error('No trigger action found')
        }

        // Set the current action to the trigger action
        invocation.state.currentAction = {
            id: triggerAction.id,
            startedAtTimestamp: DateTime.now().toMillis(),
        }

        const nextAction = findContinueAction(invocation)
        if (!nextAction) {
            throw new Error('No next action found')
        }

        invocation.state.currentAction = {
            id: nextAction.id,
            startedAtTimestamp: DateTime.now().toMillis(),
        }

        return nextAction
    }

    return findActionById(invocation.hogFlow, invocation.state.currentAction.id)
}

export function findContinueAction(invocation: CyclotronJobInvocationHogFlow): HogFlowAction {
    const currentActionId = invocation.state.currentAction?.id
    if (!currentActionId) {
        throw new Error('Cannot find continue action without a current action')
    }

    return findNextAction(invocation.hogFlow, currentActionId)
}

export async function shouldSkipAction(
    invocation: CyclotronJobInvocationHogFlow,
    action: HogFlowAction
): Promise<boolean> {
    if (!action.filters) {
        return false
    }

    const filterResults = await filterFunctionInstrumented({
        fn: invocation.hogFlow,
        filters: action.filters,
        filterGlobals: invocation.filterGlobals,
    })

    return !filterResults.match
}

// Special format which the frontend understands and can render as a link
export const actionIdForLogging = (action: Pick<HogFlowAction, 'id'>): string => {
    return `[Action:${action.id}]`
}
