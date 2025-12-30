import { DateTime } from 'luxon'
import { Summary } from 'prom-client'

import { CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '~/cdp/types'
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

const DELAY_ACTION_TYPES: HogFlowAction['type'][] = ['delay', 'wait_until_condition', 'wait_until_time_window']

export function hasDelayActions(actions: HogFlowAction[]): boolean {
    return actions.some((action) => DELAY_ACTION_TYPES.includes(action.type))
}

const workflowE2eLagMsSummary = new Summary({
    name: 'workflow_e2e_lag_ms',
    help: 'Time difference in ms between event capture time and workflow finishing time',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

/**
 * Intended to measure the time between when the event was captured and when the workflow finished.
 */
export function trackE2eLag(result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>): void {
    if (!result.finished) {
        return
    }

    const capturedAt = result.invocation.state.event?.captured_at
    // We're ignoring hogflows with delay actions for now because they're hard to track accurately (may or may not have run)
    const hasDelay = hasDelayActions(result.invocation.hogFlow.actions)

    if (capturedAt && !hasDelay) {
        const e2eLagMs = Date.now() - new Date(capturedAt).getTime()
        workflowE2eLagMsSummary.observe(e2eLagMs)
    }
}
