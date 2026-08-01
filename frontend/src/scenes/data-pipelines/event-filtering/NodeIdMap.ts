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
 * Object identity alone is not enough for the nodes an edit actually touches:
 * updateAtPath rebuilds the target node and every ancestor along its path, so
 * those arrive as fresh objects. buildIndex therefore falls back to matching a
 * rebuilt node against whatever occupied its path on the previous build.
 *
 * The instance is owned by the scene component (via useRef) and passed
 * down to the tree editor. This avoids module-level global state.
 */

let nidCounter = 0

const pathKey = (path: TreePath): string => path.join('/')

export class NodeIdMap {
    private ids = new WeakMap<FilterNode, string>()
    private pathIndex: Map<string, TreePath> = new Map()
    private nidByPath: Map<string, string> = new Map()

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
        const previousNidByPath = this.nidByPath
        // Nodes that survived the mutation with their identity intact keep their ID, so gather
        // those before assigning anything. An ID still held by a live node must never be
        // inherited by a rebuilt one, or two nodes would share a key.
        const claimed = new Set<string>()
        this.collectClaimed(node, claimed)

        this.pathIndex = new Map()
        this.nidByPath = new Map()
        this.indexNode(node, [], previousNidByPath, claimed)
    }

    private collectClaimed(node: FilterNode, claimed: Set<string>): void {
        const existing = this.ids.get(node)
        if (existing) {
            claimed.add(existing)
        }
        this.eachChild(node, (child) => this.collectClaimed(child, claimed))
    }

    private indexNode(
        node: FilterNode,
        path: TreePath,
        previousNidByPath: Map<string, string>,
        claimed: Set<string>
    ): void {
        let id = this.ids.get(node)
        if (!id) {
            // Typing a character replaces the edited node and its ancestors, so minting a new ID
            // here would change their React keys and remount the subtree, dropping focus from the
            // input mid-word. A rebuilt node standing where its predecessor stood is the same node
            // as far as the user is concerned, so it inherits that ID.
            const inherited = previousNidByPath.get(pathKey(path))
            id = inherited !== undefined && !claimed.has(inherited) ? inherited : `n${nidCounter++}`
            claimed.add(id)
            this.ids.set(node, id)
        }
        this.pathIndex.set(id, path)
        this.nidByPath.set(pathKey(path), id)
        this.eachChild(node, (child, step) => this.indexNode(child, [...path, step], previousNidByPath, claimed))
    }

    private eachChild(node: FilterNode, fn: (child: FilterNode, step: 'child' | number) => void): void {
        if (node.type === 'and' || node.type === 'or') {
            node.children.forEach((child, i) => fn(child, i))
        } else if (node.type === 'not') {
            fn(node.child, 'child')
        }
    }

    /** Look up the TreePath for a given nid, or undefined if not in the current index. */
    pathOf(nid: string): TreePath | undefined {
        return this.pathIndex.get(nid)
    }
}
