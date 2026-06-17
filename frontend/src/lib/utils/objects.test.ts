import { areObjectValuesEmpty, objectClean, objectCleanWithEmpty, objectDiffShallow } from 'lib/utils/objects'

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
})
