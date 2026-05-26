import { FilterNode, FilterAndNode, FilterOrNode } from './eventFilterLogic'
import { resolveDropTarget, reorderWithinGroup, moveBetweenGroups } from './filterTreeDnd'
import { NodeIdMap } from './NodeIdMap'
import { cond, and, or, not } from './testHelpers'

function indexed(tree: FilterNode): NodeIdMap {
    const nodeIds = new NodeIdMap()
    nodeIds.buildIndex(tree)
    return nodeIds
}

describe('resolveDropTarget', () => {
    const condA = cond('event_name', 'exact', 'a')
    const condB = cond('event_name', 'exact', 'b')
    const condC = cond('event_name', 'exact', 'c')
    const tree = or(condA, and(condB, condC))
    const nodeIds = indexed(tree)
    const innerAnd = tree.children[1]

    it('resolves drop on a group droppable → append at end', () => {
        const result = resolveDropTarget(`drop:${nodeIds.nidOf(innerAnd)}`, tree, nodeIds)
        expect(result).toEqual({ groupPath: [1], insertIndex: 2 })
    })

    it('resolves drop on root group droppable', () => {
        const result = resolveDropTarget(`drop:${nodeIds.nidOf(tree)}`, tree, nodeIds)
        expect(result).toEqual({ groupPath: [], insertIndex: 2 })
    })

    it('resolves drop on a sortable item → insert at its position', () => {
        const result = resolveDropTarget(nodeIds.nidOf(condB), tree, nodeIds)
        expect(result).toEqual({ groupPath: [1], insertIndex: 0 })
    })

    it('returns null for unknown nid', () => {
        expect(resolveDropTarget('unknown', tree, nodeIds)).toBeNull()
        expect(resolveDropTarget('drop:unknown', tree, nodeIds)).toBeNull()
    })

    it('returns null if drop target is a condition (not a group)', () => {
        expect(resolveDropTarget(`drop:${nodeIds.nidOf(condA)}`, tree, nodeIds)).toBeNull()
    })
})

describe('reorderWithinGroup', () => {
    const mockArrayMove = (arr: FilterNode[], from: number, to: number): FilterNode[] => {
        const result = [...arr]
        const [item] = result.splice(from, 1)
        result.splice(to, 0, item)
        return result
    }

    it('reorders children in root group', () => {
        const a = cond('event_name', 'exact', 'a')
        const b = cond('event_name', 'exact', 'b')
        const c = cond('event_name', 'exact', 'c')
        const tree = or(a, b, c)

        const result = reorderWithinGroup(tree, [], 0, 2, mockArrayMove)
        expect(result).toEqual(or(b, c, a))
    })

    it('reorders children in a nested group', () => {
        const a = cond('event_name', 'exact', 'a')
        const b = cond('event_name', 'exact', 'b')
        const tree = or(and(a, b))

        const result = reorderWithinGroup(tree, [0], 0, 1, mockArrayMove)
        expect(result).toEqual(and(b, a))
    })

    it('returns null if path points to a condition', () => {
        const tree = or(cond())
        expect(reorderWithinGroup(tree, [0], 0, 1, mockArrayMove)).toBeNull()
    })

    it('returns null if path points to a NOT node', () => {
        const tree = or(not(cond()))
        expect(reorderWithinGroup(tree, [0], 0, 1, mockArrayMove)).toBeNull()
    })

    it('no-op reorder (same index) returns identical structure', () => {
        const a = cond('event_name', 'exact', 'a')
        const b = cond('event_name', 'exact', 'b')
        const tree = or(a, b)
        const result = reorderWithinGroup(tree, [], 0, 0, mockArrayMove)
        expect(result).toEqual(or(a, b))
    })
})

describe('moveBetweenGroups', () => {
    it('moves a node from one group to another', () => {
        const a = cond('event_name', 'exact', 'a')
        const b = cond('event_name', 'exact', 'b')
        const c = cond('event_name', 'exact', 'c')
        const secondAnd = and(c)
        const tree = or(and(a, b), secondAnd)
        const nodeIds = indexed(tree)

        const result = moveBetweenGroups(tree, [0], 0, nodeIds.nidOf(secondAnd), 1, nodeIds)

        expect(result).not.toBeNull()
        const resultOr = result as FilterOrNode
        const firstAnd = resultOr.children[0] as FilterAndNode
        const secondAndResult = resultOr.children[1] as FilterAndNode
        expect(firstAnd.children).toHaveLength(1)
        expect(firstAnd.children[0]).toMatchObject({ value: 'b' })
        expect(secondAndResult.children).toHaveLength(2)
        expect(secondAndResult.children[0]).toMatchObject({ value: 'c' })
        expect(secondAndResult.children[1]).toMatchObject({ value: 'a' })
    })

    it('returns null if source is not a group', () => {
        const tree = not(cond())
        const nodeIds = indexed(tree)
        expect(moveBetweenGroups(tree, [], 0, 'anything', 0, nodeIds)).toBeNull()
    })

    it('does not mutate the original tree', () => {
        const a = cond('event_name', 'exact', 'a')
        const b = cond('event_name', 'exact', 'b')
        const c = cond('event_name', 'exact', 'c')
        const secondAnd = and(c)
        const tree = or(and(a, b), secondAnd)
        const nodeIds = indexed(tree)
        const original = JSON.parse(JSON.stringify(tree))

        moveBetweenGroups(tree, [0], 0, nodeIds.nidOf(secondAnd), 1, nodeIds)

        expect(tree).toEqual(original)
    })

    it('moves last child out of a group (leaves it empty)', () => {
        const a = cond('event_name', 'exact', 'a')
        const b = cond('event_name', 'exact', 'b')
        const secondAnd = and(b)
        const tree = or(and(a), secondAnd)
        const nodeIds = indexed(tree)

        const result = moveBetweenGroups(tree, [0], 0, nodeIds.nidOf(secondAnd), 1, nodeIds)

        expect(result).not.toBeNull()
        const resultOr = result as FilterOrNode
        expect((resultOr.children[0] as FilterAndNode).children).toHaveLength(0)
        expect((resultOr.children[1] as FilterAndNode).children).toHaveLength(2)
    })

    it('moves a node to root group', () => {
        const a = cond('event_name', 'exact', 'a')
        const b = cond('event_name', 'exact', 'b')
        const tree = or(and(a, b))
        const nodeIds = indexed(tree)

        // Move condA from the inner AND to the root OR at index 1
        const result = moveBetweenGroups(tree, [0], 0, nodeIds.nidOf(tree), 1, nodeIds)

        expect(result).not.toBeNull()
        const resultOr = result as FilterOrNode
        expect(resultOr.children).toHaveLength(2)
        expect((resultOr.children[0] as FilterAndNode).children).toHaveLength(1)
        expect(resultOr.children[1]).toMatchObject({ value: 'a' })
    })

    it('handles index shift when source and dest share a parent', () => {
        // OR(condA, AND(condB, condC))
        // Drag condA (index 0 in root OR) into the AND group (index 1 in root OR)
        // After removing condA, the AND group shifts from index 1 to index 0
        // Using nid-based resolution avoids the off-by-one
        const condA = cond('event_name', 'exact', 'a')
        const condB = cond('event_name', 'exact', 'b')
        const condC = cond('event_name', 'exact', 'c')
        const innerAnd = and(condB, condC)
        const tree = or(condA, innerAnd)
        const nodeIds = indexed(tree)

        const result = moveBetweenGroups(tree, [], 0, nodeIds.nidOf(innerAnd), 2, nodeIds)

        expect(result).not.toBeNull()
        const resultOr = result as FilterOrNode
        expect(resultOr.children).toHaveLength(1)
        const andGroup = resultOr.children[0] as FilterAndNode
        expect(andGroup.children).toHaveLength(3)
        expect(andGroup.children[0]).toMatchObject({ value: 'b' })
        expect(andGroup.children[1]).toMatchObject({ value: 'c' })
        expect(andGroup.children[2]).toMatchObject({ value: 'a' })
    })
})
