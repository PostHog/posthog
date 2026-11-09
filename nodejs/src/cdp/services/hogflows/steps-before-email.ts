import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'

import { frequencyCapCanHold } from '../messaging/recipient-preferences.service'

const WAITING_ACTION_TYPES: ReadonlySet<HogFlowAction['type']> = new Set([
    'delay',
    'wait_until_condition',
    'wait_until_time_window',
])

const canWait = (action: HogFlowAction): boolean => WAITING_ACTION_TYPES.has(action.type) || frequencyCapCanHold(action)

const successorsOf = (hogFlow: HogFlow, id: string): string[] =>
    hogFlow.edges.filter((edge) => edge.from === id).map((edge) => edge.to)

const reachableFrom = (hogFlow: HogFlow, startIds: string[]): Set<string> => {
    const reached = new Set<string>()
    const toVisit = [...startIds]
    while (toVisit.length > 0) {
        const id = toVisit.pop()!
        if (reached.has(id)) {
            continue
        }
        reached.add(id)
        toVisit.push(...successorsOf(hogFlow, id))
    }
    return reached
}

const reachesAnEmail = (hogFlow: HogFlow, startIds: string[]): boolean => {
    const reached = reachableFrom(hogFlow, startIds)
    return hogFlow.actions.some((action) => action.type === 'function_email' && reached.has(action.id))
}

const holdsAnEmail = (hogFlow: HogFlow, action: HogFlowAction): boolean => reachesAnEmail(hogFlow, [action.id])

const anEmailFollows = (hogFlow: HogFlow, action: HogFlowAction): boolean =>
    reachesAnEmail(hogFlow, successorsOf(hogFlow, action.id))

const setsVariables = (action: HogFlowAction): boolean => {
    const outputVariables = Array.isArray(action.output_variable)
        ? action.output_variable
        : action.output_variable
          ? [action.output_variable]
          : []
    return outputVariables.some((outputVariable) => Boolean(outputVariable.key))
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

const stepThatCanWaitBeforeEmail = (hogFlow: HogFlow): HogFlowAction | null => {
    const reachable = reachableFromTrigger(hogFlow)
    return (
        hogFlow.actions.find(
            (action) => reachable.has(action.id) && canWait(action) && holdsAnEmail(hogFlow, action)
        ) ?? null
    )
}

export const stepThatSetsVariablesBeforeEmail = (hogFlow: HogFlow): HogFlowAction | null => {
    const reachable = reachableFromTrigger(hogFlow)
    return (
        hogFlow.actions.find(
            (action) => reachable.has(action.id) && setsVariables(action) && anEmailFollows(hogFlow, action)
        ) ?? null
    )
}

export type WorkflowRefusalForFiles = {
    error: 'workflow_can_wait' | 'workflow_sets_variables_before_email'
    reason: string
    fix: string
}

export const workflowRefusalForFiles = (hogFlow: HogFlow): WorkflowRefusalForFiles | null => {
    const stepThatCanWait = stepThatCanWaitBeforeEmail(hogFlow)
    if (stepThatCanWait) {
        return {
            error: 'workflow_can_wait',
            reason: `The "${stepThatCanWait.name}" step can hold this send before its email goes out, so its files could expire first.`,
            fix: 'Send files through a workflow whose transactional email step follows the trigger directly, or send this email without files.',
        }
    }
    const stepThatSetsVariables = stepThatSetsVariablesBeforeEmail(hogFlow)
    if (stepThatSetsVariables) {
        return {
            error: 'workflow_sets_variables_before_email',
            reason: `The "${stepThatSetsVariables.name}" step stores its output in a workflow variable before an email step, so that email could render larger than the size checked for its files.`,
            fix: 'Send files through a workflow with no step that stores an output variable before its email step, or send this email without files.',
        }
    }
    return null
}
