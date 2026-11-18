import type { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

const MODELS_ROOT = 'models'

type NamespaceGroup = { path: string; groups: Map<string, NamespaceGroup>; leaves: TreeDataItem[] }

const label = (item: TreeDataItem): string => (typeof item.displayName === 'string' ? item.displayName : item.name)

export const byLabel = (left: TreeDataItem, right: TreeDataItem): number => label(left).localeCompare(label(right))

const segmentsBelowRoot = (name: string): string[] | null => {
    const segments = name.split('.')
    return segments.length >= 2 && segments[0] === MODELS_ROOT ? segments.slice(1) : null
}

export const folderNameToModelSegment = (folderName: string): string => {
    const segment = folderName
        .toLowerCase()
        .replace(/[^a-z0-9_]/g, '_')
        .replace(/_+/g, '_')
        .replace(/^_|_$/g, '')
    return /^[0-9]/.test(segment) ? `_${segment}` : segment
}

/** The name a model takes in a folder, or at the root when `folderName` is null. Null when the folder name has no usable segment. */
export const modelNameForFolder = (modelName: string, folderName: string | null): string | null => {
    const leaf = modelName.split('.').pop() ?? modelName
    if (folderName === null) {
        return leaf
    }
    const segment = folderNameToModelSegment(folderName)
    return segment ? `${segment}.${leaf}` : null
}

/** True when `proposedName` names the stored model, given that the backend stores a bare name under the models root. */
export const isSameModelName = (storedName: string, proposedName: string): boolean =>
    storedName === proposedName || storedName === `${MODELS_ROOT}.${proposedName}`

// Only the shown name changes; `name` keeps the full listed name that click, insert and join use.
export const withoutModelsRoot = (node: TreeDataItem, folderName?: string): TreeDataItem => {
    const segments = segmentsBelowRoot(node.name)
    if (!segments) {
        return node
    }
    // The folder already shows its segment, so a model named after it shows only the rest.
    const folderSegment = folderName === undefined ? null : folderNameToModelSegment(folderName)
    const shown = segments.length > 1 && segments[0] === folderSegment ? segments.slice(1) : segments
    return { ...node, displayName: shown.join('.') }
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
