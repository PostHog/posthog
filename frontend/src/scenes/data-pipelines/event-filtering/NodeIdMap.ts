import type { FilterNode, TreePath } from './eventFilterLogic'

/**
 * Maps FilterNode object references to stable string IDs for DnD.
 *
 * DnD needs stable IDs for each node. Array indices don't work because they
 * shift when siblings are added/removed/reordered. NodeIdMap assigns each
 * node a stable string ID via a WeakMap keyed by object identity. Since
 * updateAtPath uses structural sharing (unchanged subtrees keep their
 * references), unchanged nodes keep their IDs across tree mutations.
 *
 * An edit replaces the edited node and copies each of its ancestors, so these
 * nodes are new objects. buildIndex gives each new object the ID of the node
 * that was at the same path before, if that node is no longer in the tree.
 * The editor uses the IDs as React keys, so an edit does not remount the row
 * and the input that the user types in keeps focus.
 *
 * The instance is owned by the scene component (via useRef) and passed
 * down to the tree editor. This avoids module-level global state.
 */

let nidCounter = 0

function pathKey(path: TreePath): string {
    return path.join('.')
}

function childEntries(node: FilterNode): [FilterNode, TreePath[number]][] {
    if (node.type === 'and' || node.type === 'or') {
        return node.children.map((child, i) => [child, i])
    }
    if (node.type === 'not') {
        return [[node.child, 'child']]
    }
    return []
}

export class NodeIdMap {
    private ids = new WeakMap<FilterNode, string>()
    private pathIndex: Map<string, TreePath> = new Map()

    /** Get or assign a stable ID for a node. */
    nidOf(node: FilterNode): string {
        let id = this.ids.get(node)
        if (!id) {
            id = `n${nidCounter++}`
            this.ids.set(node, id)
        }
        return id
    }

    /**
     * Rebuild the nid → TreePath index for the given tree.
     * Call this once per render before using pathOf().
     */
    buildIndex(node: FilterNode): void {
        const previousNidByPath = new Map(Array.from(this.pathIndex, ([nid, path]) => [pathKey(path), nid]))
        const usedNids = new Set<string>()
        this.collectKnownNids(node, usedNids)
        this.pathIndex = new Map()
        this.indexNode(node, [], previousNidByPath, usedNids)
    }

    private collectKnownNids(node: FilterNode, nids: Set<string>): void {
        const id = this.ids.get(node)
        if (id) {
            nids.add(id)
        }
        for (const [child] of childEntries(node)) {
            this.collectKnownNids(child, nids)
        }
    }

    private indexNode(
        node: FilterNode,
        path: TreePath,
        previousNidByPath: Map<string, string>,
        usedNids: Set<string>
    ): void {
        if (!this.ids.has(node)) {
            // The previous ID is still in use when the old node moved, for example into a new NOT wrapper.
            const previousNid = previousNidByPath.get(pathKey(path))
            if (previousNid && !usedNids.has(previousNid)) {
                this.ids.set(node, previousNid)
                usedNids.add(previousNid)
            }
        }
        this.pathIndex.set(this.nidOf(node), path)
        for (const [child, step] of childEntries(node)) {
            this.indexNode(child, [...path, step], previousNidByPath, usedNids)
        }
    }

    /** Look up the TreePath for a given nid, or undefined if not in the current index. */
    pathOf(nid: string): TreePath | undefined {
        return this.pathIndex.get(nid)
    }
}
