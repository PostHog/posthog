import { HogFlow, HogFlowAction } from '~/schema/hogflow'

export const findActionById = (hogFlow: HogFlow, id: string): HogFlowAction => {
    const action = hogFlow.actions.find((action) => action.id === id)
    if (!action) {
        throw new Error(`Action ${id} not found`)
    }

    return action
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
