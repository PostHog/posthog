import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'

export type EmailStep = Extract<HogFlowAction, { type: 'function_email' }>

export type FilesWorkflowRefusal = {
    error: 'workflow_shape_not_supported' | 'workflow_can_wait'
    reason: string
    fix: string
}

export type FilesWorkflowShape = { emailStep: EmailStep } | { refused: FilesWorkflowRefusal }

const SUPPORTED_SHAPE_FIX =
    'Send files through a workflow that has a trigger, then one transactional email step, then an exit, or send this email without files.'

const shapeNotSupported = (reason: string): FilesWorkflowShape => ({
    refused: { error: 'workflow_shape_not_supported', reason, fix: SUPPORTED_SHAPE_FIX },
})

const stepDoesNotFit = (action: HogFlowAction): FilesWorkflowShape =>
    shapeNotSupported(`The "${action.name}" step does not fit the workflow shape a send with files supports.`)

const marketingEmailCanWait = (emailStep: EmailStep): FilesWorkflowShape => ({
    refused: {
        error: 'workflow_can_wait',
        reason: `The "${emailStep.name}" step sends marketing email. Sending limits can hold it before it goes out, so its files could expire first.`,
        fix: 'Send files through a workflow whose transactional email step follows the trigger directly, or send this email without files.',
    },
})

const sendingRateLimitCanWait = (): FilesWorkflowShape => ({
    refused: {
        error: 'workflow_can_wait',
        reason: "This workflow's sending rate limit can hold this send before its email goes out, so its files could expire first.",
        fix: 'Send files through a workflow without a sending rate limit, or send this email without files.',
    },
})

const successorsById = (hogFlow: HogFlow): Map<string, string[]> => {
    const successors = new Map<string, string[]>()
    for (const edge of hogFlow.edges) {
        const known = successors.get(edge.from)
        if (known) {
            known.push(edge.to)
        } else {
            successors.set(edge.from, [edge.to])
        }
    }
    return successors
}

const reachableFromTriggerInOrder = (hogFlow: HogFlow, successors: Map<string, string[]>): HogFlowAction[] => {
    const actionsById = new Map(hogFlow.actions.map((action) => [action.id, action]))
    const reached = new Set<string>()
    const ordered: HogFlowAction[] = []
    const toVisit = hogFlow.actions.filter((action) => action.type === 'trigger').map((action) => action.id)
    for (let next = 0; next < toVisit.length; next++) {
        const id = toVisit[next]
        const action = actionsById.get(id)
        if (reached.has(id) || !action) {
            continue
        }
        reached.add(id)
        ordered.push(action)
        toVisit.push(...(successors.get(id) ?? []))
    }
    return ordered
}

const firstStepOutOfPlace = (
    successors: Map<string, string[]>,
    reachable: HogFlowAction[],
    emailStep: EmailStep
): HogFlowAction | undefined => {
    const reachableById = new Map(reachable.map((action) => [action.id, action]))
    const outOfPlaceAfter = (action: HogFlowAction, fits: (next: HogFlowAction) => boolean) =>
        (successors.get(action.id) ?? [])
            .map((id) => reachableById.get(id))
            .find((next): next is HogFlowAction => next !== undefined && !fits(next))
    for (const action of reachable) {
        const outOfPlace =
            action.type === 'trigger'
                ? outOfPlaceAfter(action, (next) => next.id === emailStep.id)
                : action.id === emailStep.id
                  ? outOfPlaceAfter(action, (next) => next.type === 'exit')
                  : undefined
        if (outOfPlace) {
            return outOfPlace
        }
    }
    return undefined
}

export const filesWorkflowShape = (hogFlow: HogFlow): FilesWorkflowShape => {
    const successors = successorsById(hogFlow)
    const reachable = reachableFromTriggerInOrder(hogFlow, successors)
    let emailStep: EmailStep | undefined
    for (const action of reachable) {
        if (action.type === 'function_email' && !emailStep) {
            emailStep = action
        } else if (action.type !== 'trigger' && action.type !== 'exit') {
            return stepDoesNotFit(action)
        }
    }
    if (!emailStep) {
        return shapeNotSupported('This workflow has no email step after its trigger.')
    }
    const outOfPlace = firstStepOutOfPlace(successors, reachable, emailStep)
    if (outOfPlace) {
        return stepDoesNotFit(outOfPlace)
    }
    if (emailStep.config.message_category_type !== 'transactional') {
        return marketingEmailCanWait(emailStep)
    }
    return hogFlow.email_sending_rate_limit ? sendingRateLimitCanWait() : { emailStep }
}
