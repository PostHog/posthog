import {
    areObjectValuesEmpty,
    objectClean,
    objectCleanWithEmpty,
    objectDiffShallow,
    reconcileById,
} from 'lib/utils/objects'

describe('objects utils', () => {
    describe('areObjectValuesEmpty()', () => {
        it('returns correct value for objects with empty values', () => {
            expect(areObjectValuesEmpty({ a: '', b: null, c: undefined })).toEqual(true)
            expect(areObjectValuesEmpty({ a: undefined, b: undefined })).toEqual(true)
            expect(areObjectValuesEmpty({})).toEqual(true)
        })
        it('returns correct value for objects with at least one non-empty value', () => {
            expect(areObjectValuesEmpty({ a: '', b: null, c: 'hello' })).toEqual(false)
            expect(areObjectValuesEmpty({ a: true, b: 'hello' })).toEqual(false)
            expect(areObjectValuesEmpty('hello' as any)).toEqual(false)
            expect(areObjectValuesEmpty(null as any)).toEqual(false)
        })
    })

    describe('objectDiffShallow()', () => {
        it('obj1 + result = obj2', () => {
            expect(objectDiffShallow({ b: '4' }, { b: '3', a: '2' })).toStrictEqual({ b: '3', a: '2' })
            expect(objectDiffShallow({ b: '4', c: '12' }, { b: '3', a: '2' })).toStrictEqual({
                b: '3',
                a: '2',
                c: undefined,
            })
        })
    })

    describe('objectClean()', () => {
        it('removes undefined values', () => {
            expect(objectClean({ a: 1, b: 'b', c: null, d: {}, e: [], f: undefined })).toStrictEqual({
                a: 1,
                b: 'b',
                c: null,
                d: {},
                e: [],
            })
        })
    })

    describe('objectCleanWithEmpty()', () => {
        it('removes undefined and empty values', () => {
            expect(
                objectCleanWithEmpty({ a: 1, b: 'b', c: null, d: {}, e: [], f: undefined, g: { x: 1 }, h: [1] })
            ).toStrictEqual({
                a: 1,
                b: 'b',
                c: null,
                g: { x: 1 },
                h: [1],
            })
        })
    })

    describe('reconcileById()', () => {
        type Item = { id: string; status: string; count: number }
        const makeItem = (overrides: Partial<Item> = {}): Item => ({ id: 'a', status: 'done', count: 0, ...overrides })

        it('keeps the previous reference for unchanged items and the fresh one for changed items', () => {
            // A poll returns freshly parsed objects; reconcileById is what preserves identity so
            // memoized rows only re-render on real change. If it degrades to `return next`,
            // unchanged items churn references every poll and React.memo is silently defeated.
            const prevUnchanged = makeItem({ id: 'a', count: 1 })
            const prevChanged = makeItem({ id: 'b', status: 'running' })

            const nextUnchanged = makeItem({ id: 'a', count: 1 })
            const nextChanged = makeItem({ id: 'b', status: 'done' })
            const nextNew = makeItem({ id: 'c' })

            const result = reconcileById(
                [prevUnchanged, prevChanged],
                [nextUnchanged, nextChanged, nextNew],
                (item) => item.id
            )

            expect(result[0]).toBe(prevUnchanged)
            expect(result[1]).toBe(nextChanged)
            expect(result[2]).toBe(nextNew)
        })

        it('returns the next array untouched when there is no previous list', () => {
            const next = [makeItem()]
            expect(reconcileById([], next, (item) => item.id)).toBe(next)
        })

        it('never reuses items the isReusable predicate rejects, even when deep-equal', () => {
            // An in-flight item's row may render wall-clock time: reusing its reference would let a
            // memoized row skip the poll re-render and freeze.
            const prev = makeItem({ status: 'running' })
            const next = makeItem({ status: 'running' })
            const result = reconcileById(
                [prev],
                [next],
                (item) => item.id,
                (item) => item.status !== 'running'
            )
            expect(result[0]).toBe(next)
        })
    })
})
