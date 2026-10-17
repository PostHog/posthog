import { FilterNode, TreePath, updateAtPath } from './eventFilterLogic'
import { NodeIdMap } from './NodeIdMap'
import { cond, and, or, not } from './testHelpers'

function nidsInOrder(nodeIds: NodeIdMap, node: FilterNode): string[] {
    const own = nodeIds.nidOf(node)
    if (node.type === 'and' || node.type === 'or') {
        return [own, ...node.children.flatMap((child) => nidsInOrder(nodeIds, child))]
    }
    if (node.type === 'not') {
        return [own, ...nidsInOrder(nodeIds, node.child)]
    }
    return [own]
}

describe('NodeIdMap', () => {
    describe('nidOf', () => {
        it('assigns a non-empty string ID', () => {
            const nodeIds = new NodeIdMap()
            expect(nodeIds.nidOf(cond())).not.toBe('')
        })

        it('returns the same ID for the same object reference', () => {
            const nodeIds = new NodeIdMap()
            const node = cond()
            expect(nodeIds.nidOf(node)).toBe(nodeIds.nidOf(node))
        })

        it('returns different IDs for different objects', () => {
            const nodeIds = new NodeIdMap()
            expect(nodeIds.nidOf(cond())).not.toBe(nodeIds.nidOf(cond()))
        })

        it('preserves IDs across buildIndex calls', () => {
            const nodeIds = new NodeIdMap()
            const node = cond()
            const tree = or(node)
            nodeIds.buildIndex(tree)
            const first = nodeIds.nidOf(node)
            nodeIds.buildIndex(tree)
            expect(nodeIds.nidOf(node)).toBe(first)
        })
    })

    describe('buildIndex and pathOf', () => {
        it('indexes a single condition at root', () => {
            const nodeIds = new NodeIdMap()
            const tree = cond()
            nodeIds.buildIndex(tree)
            expect(nodeIds.pathOf(nodeIds.nidOf(tree))).toEqual([])
        })

        it('indexes AND/OR children with numeric paths', () => {
            const nodeIds = new NodeIdMap()
            const c0 = cond('event_name', 'exact', 'a')
            const c1 = cond('event_name', 'exact', 'b')
            const tree = or(c0, c1)
            nodeIds.buildIndex(tree)

            expect(nodeIds.pathOf(nodeIds.nidOf(tree))).toEqual([])
            expect(nodeIds.pathOf(nodeIds.nidOf(c0))).toEqual([0])
            expect(nodeIds.pathOf(nodeIds.nidOf(c1))).toEqual([1])
        })

        it('indexes NOT child with "child" step', () => {
            const nodeIds = new NodeIdMap()
            const inner = cond()
            const tree = not(inner)
            nodeIds.buildIndex(tree)

            expect(nodeIds.pathOf(nodeIds.nidOf(tree))).toEqual([])
            expect(nodeIds.pathOf(nodeIds.nidOf(inner))).toEqual(['child'])
        })

        it('indexes a deep tree', () => {
            const nodeIds = new NodeIdMap()
            const leaf = cond()
            const tree = and(or(leaf, cond()), not(cond()))
            nodeIds.buildIndex(tree)

            expect(nodeIds.pathOf(nodeIds.nidOf(leaf))).toEqual([0, 0])
        })

        it('returns undefined for unknown nid', () => {
            const nodeIds = new NodeIdMap()
            nodeIds.buildIndex(cond())
            expect(nodeIds.pathOf('nonexistent')).toBeUndefined()
        })

        it('rebuilds index correctly after tree mutation', () => {
            const nodeIds = new NodeIdMap()
            const c0 = cond('event_name', 'exact', 'a')
            const c1 = cond('event_name', 'exact', 'b')
            const tree1 = or(c0, c1)
            nodeIds.buildIndex(tree1)
            expect(nodeIds.pathOf(nodeIds.nidOf(c0))).toEqual([0])

            // Simulate removing c0 — c1 is now at index 0
            const tree2 = or(c1)
            nodeIds.buildIndex(tree2)
            expect(nodeIds.pathOf(nodeIds.nidOf(c1))).toEqual([0])
            // c0 is no longer in the index
            expect(nodeIds.pathOf(nodeIds.nidOf(c0))).toBeUndefined()
        })

        it.each<[string, TreePath]>([
            ['a nested condition', [0, 1]],
            ['a nested group', [0]],
        ])('keeps every ID when an edit replaces %s and copies its ancestors', (_, path) => {
            const nodeIds = new NodeIdMap()
            const tree = or(and(cond('event_name', 'exact', 'a'), cond('event_name', 'exact', 'b')), cond())
            nodeIds.buildIndex(tree)
            const before = nidsInOrder(nodeIds, tree)

            const edited = updateAtPath(tree, path, (node) => ({ ...node, comment: 'why' }))
            nodeIds.buildIndex(edited)

            expect(nidsInOrder(nodeIds, edited)).toEqual(before)
        })

        it('gives a new NOT wrapper its own ID and keeps the wrapped node ID', () => {
            const nodeIds = new NodeIdMap()
            const inner = cond()
            const tree = or(inner)
            nodeIds.buildIndex(tree)
            const innerNid = nodeIds.nidOf(inner)

            const wrapped = updateAtPath(tree, [0], (node) => not(node))
            nodeIds.buildIndex(wrapped)

            expect(nodeIds.pathOf(innerNid)).toEqual([0, 'child'])
            expect(nodeIds.pathOf(nodeIds.nidOf((wrapped as typeof tree).children[0]))).toEqual([0])
        })
    })
})
