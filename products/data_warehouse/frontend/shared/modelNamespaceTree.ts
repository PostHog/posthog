import type { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

const MODELS_ROOT = 'models'

type NamespaceGroup = { path: string; groups: Map<string, NamespaceGroup>; leaves: TreeDataItem[] }

const label = (item: TreeDataItem): string => (typeof item.displayName === 'string' ? item.displayName : item.name)

const byLabel = (left: TreeDataItem, right: TreeDataItem): number => label(left).localeCompare(label(right))

// Groups derive from the listed name, never from the saved query's folder, so only a rename moves a model between groups.
// Groups derive from the listed name, never from the saved query's folder, so only a rename moves a model between groups.
export const groupModelsByNamespace = (
    nodes: TreeDataItem[],
    isSearch: boolean
): { items: TreeDataItem[]; groupIds: string[] } => {
    const root: NamespaceGroup = { path: MODELS_ROOT, groups: new Map(), leaves: [] }
    const ungrouped: TreeDataItem[] = []

    for (const node of nodes) {
        const segments = node.name.split('.')
        if (segments.length < 2 || segments[0] !== MODELS_ROOT) {
            ungrouped.push(node)
            continue
        }
        let group = root
        for (const segment of segments.slice(1, -1)) {
            let child = group.groups.get(segment)
            if (!child) {
                child = { path: `${group.path}.${segment}`, groups: new Map(), leaves: [] }
                group.groups.set(segment, child)
            }
            group = child
        }
        group.leaves.push({ ...node, displayName: segments[segments.length - 1] })
    }

    if (root.leaves.length === 0 && root.groups.size === 0) {
        return { items: nodes, groupIds: [] }
    }

    const groupIds: string[] = []
    const toTreeItem = (name: string, group: NamespaceGroup): TreeDataItem => {
        const id = `${isSearch ? 'search-' : ''}model-namespace-${group.path}`
        groupIds.push(id)
        return {
            id,
            name,
            type: 'node',
            record: { type: 'model-namespace', path: group.path },
            children: [
                ...Array.from(group.groups.entries()).map(([segment, child]) => toTreeItem(segment, child)),
                ...group.leaves,
            ].sort(byLabel),
        }
    }

    return { items: [toTreeItem(MODELS_ROOT, root), ...ungrouped], groupIds }
}
