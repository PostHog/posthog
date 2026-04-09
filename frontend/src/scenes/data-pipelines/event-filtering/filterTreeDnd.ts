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
 * Move a node from one AND/OR group to another.
 *
 * Deep-clones the tree (can't use immutable updateAtPath since we need to
 * mutate two places), splices the node out of the source group, then
 * splices it into the destination group. Returns the new tree root, or
 * null if either the source or destination can't be resolved.
 *
 * The destination is specified as a group path + insert index. The caller
 * is responsible for resolving the drop target (via resolveDropTarget)
 * before calling this function.
 *
 * Note: if the source and destination are in the same parent and the
 * source index is before the destination index, the caller should adjust
 * destIndex by -1 to account for the removal shifting indices.
 */
export function moveBetweenGroups(
    tree: FilterNode,
    sourcePath: TreePath,
    sourceIndex: number,
    destPath: TreePath,
    destIndex: number
): FilterNode | null {
    const srcParent = sourcePath.length === 0 ? tree : getNodeAtPath(tree, sourcePath)
    if (!srcParent || (srcParent.type !== 'and' && srcParent.type !== 'or')) {
        return null
    }

    const movedNode = srcParent.children[sourceIndex]
    const newTree: FilterNode = JSON.parse(JSON.stringify(tree))

    // Remove from source
    const newSrc = sourcePath.length === 0 ? newTree : getNodeAtPath(newTree, sourcePath)
    if (!newSrc || (newSrc.type !== 'and' && newSrc.type !== 'or')) {
        return null
    }
    newSrc.children.splice(sourceIndex, 1)

    // Insert into destination
    const newDst = destPath.length === 0 ? newTree : getNodeAtPath(newTree, destPath)
    if (!newDst || (newDst.type !== 'and' && newDst.type !== 'or')) {
        return null
    }
    newDst.children.splice(destIndex, 0, JSON.parse(JSON.stringify(movedNode)))

    return newTree
}
