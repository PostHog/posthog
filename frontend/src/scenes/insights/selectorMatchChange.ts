import { isActionsNode } from '~/queries/utils'

const ACTIONS_ENTITY_TYPE = 'actions'

function collectActionId(node: Record<string, any> | null | undefined, actionIds: Set<number>): void {
    // A series node carries `kind: ActionsNode`, while a retention entity carries
    // `type: 'actions'` and may hold its id as a string.
    if (!node || !(isActionsNode(node) || node.type === ACTIONS_ENTITY_TYPE)) {
        return
    }
    const id = typeof node.id === 'string' ? Number(node.id) : node.id
    if (typeof id === 'number' && Number.isFinite(id)) {
        actionIds.add(id)
    }
}

export function getSelectorMatchChangeActionIds(querySource: Record<string, any> | null | undefined): number[] {
    const actionIds = new Set<number>()
    for (const node of querySource?.series ?? []) {
        collectActionId(node, actionIds)
    }
    collectActionId(querySource?.retentionFilter?.targetEntity, actionIds)
    collectActionId(querySource?.retentionFilter?.returningEntity, actionIds)
    for (const node of querySource?.funnelPathsFilter?.funnelSource?.series ?? []) {
        collectActionId(node, actionIds)
    }
    return [...actionIds].sort((left, right) => left - right)
}
