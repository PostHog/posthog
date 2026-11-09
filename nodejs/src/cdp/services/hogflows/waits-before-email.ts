import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'

import { frequencyCapCanHold } from '../messaging/recipient-preferences.service'

const WAITING_ACTION_TYPES: ReadonlySet<HogFlowAction['type']> = new Set([
    'delay',
    'wait_until_condition',
    'wait_until_time_window',
])

const canWait = (action: HogFlowAction): boolean => WAITING_ACTION_TYPES.has(action.type) || frequencyCapCanHold(action)

const reachableFrom = (hogFlow: HogFlow, startIds: string[]): Set<string> => {
    const reached = new Set<string>()
    const toVisit = [...startIds]
    while (toVisit.length > 0) {
        const id = toVisit.pop()!
        if (reached.has(id)) {
            continue
        }
        reached.add(id)
        toVisit.push(...hogFlow.edges.filter((edge) => edge.from === id).map((edge) => edge.to))
    }
    return reached
}

const holdsAnEmail = (hogFlow: HogFlow, action: HogFlowAction): boolean => {
    if (action.type === 'function_email') {
        return true
    }
    const after = reachableFrom(hogFlow, [action.id])
    return hogFlow.actions.some((later) => later.type === 'function_email' && after.has(later.id))
}

const reachableFromTrigger = (hogFlow: HogFlow): Set<string> =>
    reachableFrom(
        hogFlow,
        hogFlow.actions.filter((action) => action.type === 'trigger').map((action) => action.id)
    )

export type EmailStep = Extract<HogFlowAction, { type: 'function_email' }>

export const emailStepsReachableFromTrigger = (hogFlow: HogFlow): EmailStep[] => {
    const reachable = reachableFromTrigger(hogFlow)
    return hogFlow.actions.filter(
        (action): action is EmailStep => action.type === 'function_email' && reachable.has(action.id)
    )
}

export const stepThatCanWaitBeforeEmail = (hogFlow: HogFlow): HogFlowAction | null => {
    const reachable = reachableFromTrigger(hogFlow)
    return (
        hogFlow.actions.find(
            (action) => reachable.has(action.id) && canWait(action) && holdsAnEmail(hogFlow, action)
        ) ?? null
    )
}
