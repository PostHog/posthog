/**
 * DnD tree operations for the filter expression tree.
 *
 * Drag and drop lets users reorder conditions within a group or move them
 * between groups. The scene's handleDragEnd callback orchestrates this:
 *
 *   1. Look up the dragged node's path via its stable nid
 *   2. resolveDropTarget — figure out which group the node was dropped on
 *      and at what index (end of group if dropped on the group droppable,
 *      or at a sibling's position if dropped on a sortable item)
 *   3. Guard: bail if dropping into own descendant (would create a cycle)
 *   4. If same group → reorderWithinGroup (arrayMove within children)
 *      If different group → moveBetweenGroups (clone tree, splice out, splice in)
 *
 * All functions are pure: they take a tree and return a new tree.
 */
import { updateAtPath } from './eventFilterLogic'
import type { FilterNode, TreePath } from './eventFilterLogic'
import { getNodeAtPath, splitParentChild } from './filterTreePath'
import { NodeIdMap } from './NodeIdMap'

interface DropTarget {
    groupPath: TreePath
    insertIndex: number
}

/**
 * Determine where a dragged node should land.
 *
 * Drop target IDs come in two forms:
 *   - "drop:<nid>" — the droppable zone of a group → append at end
 *   - "<nid>" — a sortable sibling item → insert at that item's position
 *
 * Returns the target group's path and the insert index, or null if the
 * drop target can't be resolved (e.g. nid not found, target isn't a group).
 */
export function resolveDropTarget(overIdStr: string, tree: FilterNode, nodeIds: NodeIdMap): DropTarget | null {
    if (overIdStr.startsWith('drop:')) {
        // Dropped on a group droppable — append at end
        const groupNid = overIdStr.slice(5)
        const groupPath = nodeIds.pathOf(groupNid)
        if (!groupPath) {
            return null
        }
        const targetNode = groupPath.length === 0 ? tree : getNodeAtPath(tree, groupPath)
        if (!targetNode || (targetNode.type !== 'and' && targetNode.type !== 'or')) {
            return null
        }
        return { groupPath, insertIndex: targetNode.children.length }
    }
    // Dropped on a sortable item — insert at its position
    const overPath = nodeIds.pathOf(overIdStr)
    if (!overPath) {
        return null
    }
    const overParent = splitParentChild(overPath)
    if (!overParent) {
        return null
    }
    return { groupPath: overParent.parentPath, insertIndex: overParent.childIndex }
}

/**
 * Reorder a child within the same AND/OR group.
 *
 * Returns the updated group node with children reordered (caller uses
 * updateTreeNode to patch it into the tree). Returns null if the path
 * doesn't point to an AND/OR group.
 *
 * Takes arrayMove as a parameter to avoid coupling to @dnd-kit/sortable.
 */
export function reorderWithinGroup(
    tree: FilterNode,
    groupPath: TreePath,
    fromIndex: number,
    toIndex: number,
    arrayMoveFn: (arr: FilterNode[], from: number, to: number) => FilterNode[]
): FilterNode | null {
    const parentNode = groupPath.length === 0 ? tree : getNodeAtPath(tree, groupPath)
    if (!parentNode || (parentNode.type !== 'and' && parentNode.type !== 'or')) {
        return null
    }
    const newChildren = arrayMoveFn([...parentNode.children], fromIndex, toIndex)
    return { ...parentNode, children: newChildren } as FilterNode
}

/**
 * After removing sourcePath[sourceIndex], any dest path that passes through
 * the same parent at a later index needs that index decremented.
 * E.g. removing []:0 shifts dest [1,'child'] to [0,'child'].
 */
function adjustDestPath(sourcePath: TreePath, sourceIndex: number, destPath: TreePath): TreePath {
    if (destPath.length <= sourcePath.length) {
        return destPath
    }
    for (let i = 0; i < sourcePath.length; i++) {
        if (destPath[i] !== sourcePath[i]) {
            return destPath
        }
    }
    const siblingStep = destPath[sourcePath.length]
    if (typeof siblingStep === 'number' && siblingStep > sourceIndex) {
        const adjusted = [...destPath]
        adjusted[sourcePath.length] = siblingStep - 1
        return adjusted
    }
    return destPath
}

/**
 * Move a node from one AND/OR group to another.
 *
 * Resolves the destination group by nid on the original tree, then applies
 * the remove and insert as two immutable updateAtPath calls with path
 * adjustment to account for index shifts from the removal.
 */
export function moveBetweenGroups(
    tree: FilterNode,
    sourcePath: TreePath,
    sourceIndex: number,
    destGroupNid: string,
    destIndex: number,
    nodeIds: NodeIdMap
): FilterNode | null {
    const srcParent = sourcePath.length === 0 ? tree : getNodeAtPath(tree, sourcePath)
    if (!srcParent || (srcParent.type !== 'and' && srcParent.type !== 'or')) {
        return null
    }
    const movedNode = srcParent.children[sourceIndex]

    // Resolve dest path on the original tree before any mutations
    const originalDestPath = nodeIds.pathOf(destGroupNid)
    if (originalDestPath === undefined) {
        return null
    }

    // Step 1: remove from source
    const afterRemove = updateAtPath(tree, sourcePath, (node) => {
        if (node.type !== 'and' && node.type !== 'or') {
            return node
        }
        return { ...node, children: node.children.filter((_, i) => i !== sourceIndex) }
    })

    // Step 2: adjust dest path for index shift caused by the removal
    const destPath = adjustDestPath(sourcePath, sourceIndex, originalDestPath)

    // Step 3: insert into destination
    return updateAtPath(afterRemove, destPath, (node) => {
        if (node.type !== 'and' && node.type !== 'or') {
            return node
        }
        const newChildren = [...node.children]
        newChildren.splice(destIndex, 0, movedNode)
        return { ...node, children: newChildren }
    })
}
