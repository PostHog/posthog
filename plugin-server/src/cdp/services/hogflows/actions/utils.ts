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

export const findNextAction = (
    hogFlow: HogFlow,
    currentActionId: string,
    edgeIndex?: number
): HogFlowAction | undefined => {
    const edges = hogFlow.edges.filter((edge) => edge.from === currentActionId)

    let nextActionId: string | undefined

    if (edgeIndex === undefined) {
        nextActionId = edges.find((edge) => edge.type === 'continue')?.to
    } else {
        nextActionId = edges.find((edge) => edge.type === 'branch' && edge.index === edgeIndex)?.to
    }

    return nextActionId ? findActionById(hogFlow, nextActionId) : undefined
}
