import { getNodeAtPath, splitParentChild, isAncestorPath } from './filterTreePath'
import { cond, and, or, not } from './testHelpers'

describe('getNodeAtPath', () => {
    const condA = cond('event_name', 'exact', 'a')
    const condB = cond('event_name', 'exact', 'b')
    const condC = cond('distinct_id', 'exact', 'c')
    const tree = and(or(condA, condB), not(condC))

    it('returns root for empty path', () => {
        expect(getNodeAtPath(tree, [])).toBe(tree)
    })

    it('navigates into children by index', () => {
        expect(getNodeAtPath(tree, [0])).toBe(tree.children[0])
        expect(getNodeAtPath(tree, [0, 0])).toBe(condA)
        expect(getNodeAtPath(tree, [0, 1])).toBe(condB)
    })

    it('navigates through NOT with "child"', () => {
        expect(getNodeAtPath(tree, [1, 'child'])).toBe(condC)
    })

    it('returns undefined for out-of-bounds index', () => {
        expect(getNodeAtPath(tree, [5])).toBeUndefined()
    })

    it('returns undefined for invalid step type', () => {
        expect(getNodeAtPath(tree, [0, 0, 0])).toBeUndefined()
        expect(getNodeAtPath(tree, ['child'])).toBeUndefined()
    })
})

describe('splitParentChild', () => {
    it('returns null for empty path (root)', () => {
        expect(splitParentChild([])).toBeNull()
    })

    it('splits a single-step path', () => {
        expect(splitParentChild([1])).toEqual({ parentPath: [], childIndex: 1 })
    })

    it('splits a multi-step path', () => {
        expect(splitParentChild([0, 2])).toEqual({ parentPath: [0], childIndex: 2 })
    })

    it('returns null if last step is "child" (NOT node)', () => {
        expect(splitParentChild([1, 'child'])).toBeNull()
    })

    it('handles path through NOT then into group child', () => {
        expect(splitParentChild([1, 'child', 0])).toEqual({ parentPath: [1, 'child'], childIndex: 0 })
    })
})

describe('isAncestorPath', () => {
    it('empty path is ancestor of any non-empty path', () => {
        expect(isAncestorPath([], [0])).toBe(true)
        expect(isAncestorPath([], [0, 1])).toBe(true)
    })

    it('path is not its own ancestor', () => {
        expect(isAncestorPath([0], [0])).toBe(false)
        expect(isAncestorPath([], [])).toBe(false)
    })

    it('prefix match is ancestor', () => {
        expect(isAncestorPath([0], [0, 1])).toBe(true)
        expect(isAncestorPath([0, 1], [0, 1, 'child'])).toBe(true)
    })

    it('different prefix is not ancestor', () => {
        expect(isAncestorPath([0], [1, 0])).toBe(false)
        expect(isAncestorPath([0, 1], [0, 2])).toBe(false)
    })

    it('longer path is not ancestor of shorter', () => {
        expect(isAncestorPath([0, 1], [0])).toBe(false)
    })
})
