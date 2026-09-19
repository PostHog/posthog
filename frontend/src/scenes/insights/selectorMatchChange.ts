import { isActionsNode } from '~/queries/utils'

export function getSelectorMatchChangeActionIds(
    series: (Record<string, any> | null | undefined)[] | null | undefined
): number[] {
    if (!series) {
        return []
    }
    const actionIds = new Set<number>()
    for (const node of series) {
        if (isActionsNode(node)) {
            actionIds.add(node.id)
        }
    }
    return [...actionIds].sort((left, right) => left - right)
}
