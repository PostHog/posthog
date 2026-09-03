import { determineMergeMode } from './person-merge-types'

describe('determineMergeMode', () => {
    it('refuses a non-integer move limit at construction', () => {
        // It becomes the saga's move_limit and reaches BigInt() when the
        // request is built, so a fractional value would throw on every merge
        // in the deployment. This runs once, at step construction.
        expect(() => determineMergeMode(1.5, false, 0)).toThrow(
            'PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT must be an integer'
        )
    })

    it.each([
        [0, undefined],
        [-1, undefined],
    ])('treats a limit of %p as unlimited sync rather than an error', (limit, batchSize) => {
        expect(determineMergeMode(limit, true, 0)).toEqual({ type: 'SYNC', batchSize })
    })

    it.each([
        ['async enabled', true, 'ASYNC'],
        ['async disabled', false, 'LIMIT'],
    ])('%s with a positive limit selects %s', (_label, asyncEnabled, type) => {
        expect(determineMergeMode(50, asyncEnabled, 0)).toEqual({ type, limit: 50 })
    })
})
