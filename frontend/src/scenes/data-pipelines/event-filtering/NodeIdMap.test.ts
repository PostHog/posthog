import { NodeIdMap } from './NodeIdMap'
import { cond, and, or, not } from './testHelpers'

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
    })
})
