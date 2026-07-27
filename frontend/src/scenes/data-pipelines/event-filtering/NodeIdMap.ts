import type { FilterNode, TreePath } from './eventFilterLogic'

/**
 * Maps FilterNode object references to stable string IDs for DnD.
 *
 * DnD needs stable IDs for each node. Array indices don't work because they
 * shift when siblings are added/removed/reordered. NodeIdMap assigns each
 * node a stable string ID via a WeakMap keyed by object identity. Since
 * updateAtPath uses structural sharing (unchanged subtrees keep their
 * references), IDs survive across tree mutations automatically.
 *
 * The instance is owned by the scene component (via useRef) and passed
 * down to the tree editor. This avoids module-level global state.
 */

let nidCounter = 0

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
        this.pathIndex = new Map()
        this.indexNode(node, [])
    }

    private indexNode(node: FilterNode, path: TreePath): void {
        this.pathIndex.set(this.nidOf(node), path)
        if (node.type === 'and' || node.type === 'or') {
            for (let i = 0; i < node.children.length; i++) {
                this.indexNode(node.children[i], [...path, i])
            }
        } else if (node.type === 'not') {
            this.indexNode(node.child, [...path, 'child'])
        }
    }

    /** Look up the TreePath for a given nid, or undefined if not in the current index. */
    pathOf(nid: string): TreePath | undefined {
        return this.pathIndex.get(nid)
    }
}
