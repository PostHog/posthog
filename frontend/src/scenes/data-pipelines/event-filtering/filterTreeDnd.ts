import { updateAtPath } from './eventFilterLogic'
import type { FilterNode, TreePath } from './eventFilterLogic'
import { getNodeAtPath, splitParentChild } from './filterTreePath'
import { NodeIdMap } from './NodeIdMap'

interface DropTarget {
    groupPath: TreePath
    insertIndex: number
}

/**
 * Drop target IDs come in two forms:
 *   - "drop:<nid>" is the droppable zone of a group, which appends at the end
 *   - "<nid>" is a sortable sibling item, which inserts at that item's position
 */
export function resolveDropTarget(overIdStr: string, tree: FilterNode, nodeIds: NodeIdMap): DropTarget | null {
    if (overIdStr.startsWith('drop:')) {
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
 * Returns the updated group node, not the whole tree, so the caller must patch it back in
 * with updateTreeNode.
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

    // nodeIds maps to the original tree, so resolve the dest path before the removal below
    // invalidates it.
    const originalDestPath = nodeIds.pathOf(destGroupNid)
    if (originalDestPath === undefined) {
        return null
    }

    const afterRemove = updateAtPath(tree, sourcePath, (node) => {
        if (node.type !== 'and' && node.type !== 'or') {
            return node
        }
        return { ...node, children: node.children.filter((_, i) => i !== sourceIndex) }
    })

    const destPath = adjustDestPath(sourcePath, sourceIndex, originalDestPath)

    return updateAtPath(afterRemove, destPath, (node) => {
        if (node.type !== 'and' && node.type !== 'or') {
            return node
        }
        const newChildren = [...node.children]
        newChildren.splice(destIndex, 0, movedNode)
        return { ...node, children: newChildren }
    })
}
