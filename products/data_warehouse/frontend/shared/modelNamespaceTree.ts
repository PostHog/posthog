import type { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

const MODELS_ROOT = 'models'

type NamespaceGroup = { path: string; groups: Map<string, NamespaceGroup>; leaves: TreeDataItem[] }

const label = (item: TreeDataItem): string => (typeof item.displayName === 'string' ? item.displayName : item.name)

export const byLabel = (left: TreeDataItem, right: TreeDataItem): number => label(left).localeCompare(label(right))

const segmentsBelowRoot = (name: string): string[] | null => {
    const segments = name.split('.')
    return segments.length >= 2 && segments[0] === MODELS_ROOT ? segments.slice(1) : null
}

// Only the shown name changes; `name` keeps the full listed name that click, insert and join use.
export const withoutModelsRoot = (node: TreeDataItem): TreeDataItem => {
    const segments = segmentsBelowRoot(node.name)
    return segments ? { ...node, displayName: segments.join('.') } : node
}

// Groups derive from the listed name, never from the saved query's folder, so only a rename moves a model between groups.
export const groupModelsByNamespace = (
    nodes: TreeDataItem[],
    isSearch: boolean
): { items: TreeDataItem[]; groupIds: string[] } => {
    const root: NamespaceGroup = { path: MODELS_ROOT, groups: new Map(), leaves: [] }

    for (const node of nodes) {
        const segments = segmentsBelowRoot(node.name)
        if (!segments) {
            root.leaves.push(node)
            continue
        }
        let group = root
        for (const segment of segments.slice(0, -1)) {
            let child = group.groups.get(segment)
            if (!child) {
                child = { path: `${group.path}.${segment}`, groups: new Map(), leaves: [] }
                group.groups.set(segment, child)
            }
            group = child
        }
        group.leaves.push({ ...node, displayName: segments[segments.length - 1] })
    }

    const groupIds: string[] = []
    const childrenOf = (group: NamespaceGroup): TreeDataItem[] =>
        [
            ...Array.from(group.groups.entries()).map(([segment, child]) => toTreeItem(segment, child)),
            ...group.leaves,
        ].sort(byLabel)
    const toTreeItem = (name: string, group: NamespaceGroup): TreeDataItem => {
        const id = `${isSearch ? 'search-' : ''}model-namespace-${group.path}`
        groupIds.push(id)
        return {
            id,
            name,
            type: 'node',
            record: { type: 'model-namespace', path: group.path },
            children: childrenOf(group),
        }
    }

    return { items: childrenOf(root), groupIds }
}
