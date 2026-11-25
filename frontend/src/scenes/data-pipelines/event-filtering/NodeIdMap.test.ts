import { updateAtPath, type FilterNode } from './eventFilterLogic'
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

    describe('ID stability across edits', () => {
        const allNids = (nodeIds: NodeIdMap, node: FilterNode): string[] => {
            const out = [nodeIds.nidOf(node)]
            if (node.type === 'and' || node.type === 'or') {
                node.children.forEach((child) => out.push(...allNids(nodeIds, child)))
            } else if (node.type === 'not') {
                out.push(...allNids(nodeIds, node.child))
            }
            return out
        }

        // updateAtPath rebuilds the edited node and every ancestor, so identity-only IDs churned
        // on each keystroke. That changed the React keys, remounting the subtree and knocking
        // focus out of the value input after a single character.
        it('keeps IDs for the edited node and its ancestors when a value changes', () => {
            const nodeIds = new NodeIdMap()
            const tree = and(or(cond('event_name', 'exact', '')))
            nodeIds.buildIndex(tree)
            const before = allNids(nodeIds, tree)

            const edited = updateAtPath(tree, [0, 0], (n) => ({ ...(n as ReturnType<typeof cond>), value: 'a' }))
            nodeIds.buildIndex(edited)

            expect(allNids(nodeIds, edited)).toEqual(before)
        })

        it('keeps IDs stable across a run of edits, as typing a word does', () => {
            const nodeIds = new NodeIdMap()
            let tree: FilterNode = and(cond('event_name', 'exact', ''))
            nodeIds.buildIndex(tree)
            const before = allNids(nodeIds, tree)

            for (const value of ['p', 'pa', 'pag', 'page']) {
                tree = updateAtPath(tree, [0], (n) => ({ ...(n as ReturnType<typeof cond>), value }))
                nodeIds.buildIndex(tree)
            }

            expect(allNids(nodeIds, tree)).toEqual(before)
        })

        it('gives a newly added sibling its own ID rather than inheriting one', () => {
            const nodeIds = new NodeIdMap()
            const existing = cond('event_name', 'exact', 'a')
            const tree = and(existing)
            nodeIds.buildIndex(tree)
            const existingNid = nodeIds.nidOf(existing)

            const withSibling = and(existing, cond('event_name', 'exact', 'b'))
            nodeIds.buildIndex(withSibling)
            const [, firstNid, secondNid] = allNids(nodeIds, withSibling)

            expect(firstNid).toBe(existingNid)
            expect(secondNid).not.toBe(existingNid)
        })

        // Wrapping puts a brand new NOT where the condition used to sit while the condition itself
        // survives one level down. Inheriting purely by path would hand both the same ID.
        it('does not reuse a live node’s ID when a new node takes its path', () => {
            const nodeIds = new NodeIdMap()
            const inner = cond('event_name', 'exact', 'a')
            const tree = and(inner)
            nodeIds.buildIndex(tree)

            const wrapped = and(not(inner))
            nodeIds.buildIndex(wrapped)
            const nids = allNids(nodeIds, wrapped)

            expect(new Set(nids).size).toBe(nids.length)
        })
    })
})
