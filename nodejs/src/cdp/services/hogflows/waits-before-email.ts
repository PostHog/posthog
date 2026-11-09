import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'

import { frequencyCapCanHold } from '../messaging/recipient-preferences.service'

const WAITING_ACTION_TYPES: ReadonlySet<HogFlowAction['type']> = new Set([
    'delay',
    'wait_until_condition',
    'wait_until_time_window',
])

const canWait = (action: HogFlowAction): boolean => WAITING_ACTION_TYPES.has(action.type) || frequencyCapCanHold(action)

export const stepThatCanWaitBeforeEmail = (hogFlow: HogFlow): HogFlowAction | null => {
    const actions = new Map(hogFlow.actions.map((action) => [action.id, action]))
    const reached = new Set<string>()
    const toVisit = hogFlow.actions.filter((action) => action.type === 'trigger').map((action) => action.id)
    while (toVisit.length > 0) {
        const id = toVisit.pop()!
        const action = actions.get(id)
        if (reached.has(id) || !action) {
            continue
        }
        reached.add(id)
        if (canWait(action)) {
            return action
        }
        if (action.type !== 'function_email') {
            toVisit.push(...hogFlow.edges.filter((edge) => edge.from === id).map((edge) => edge.to))
        }
    }
    return null
}
