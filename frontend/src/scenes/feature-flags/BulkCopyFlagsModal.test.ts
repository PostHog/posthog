import { splitCopiedByOverwrite } from './flagSelectionLogic'

describe('splitCopiedByOverwrite', () => {
    it('returns no entries when nothing was copied', () => {
        expect(splitCopiedByOverwrite([])).toEqual({ newCopies: [], overwrites: [] })
    })

    it('puts a target with no overwrite entirely under newCopies', () => {
        const result = splitCopiedByOverwrite([{ key: 'flag-a', projectIds: [1, 2], updatedProjectIds: [] }])
        expect(result).toEqual({
            newCopies: [{ key: 'flag-a', projectIds: [1, 2] }],
            overwrites: [],
        })
    })

    it('puts a fully overwritten target entirely under overwrites', () => {
        const result = splitCopiedByOverwrite([{ key: 'flag-a', projectIds: [1, 2], updatedProjectIds: [1, 2] }])
        expect(result).toEqual({
            newCopies: [],
            overwrites: [{ key: 'flag-a', projectIds: [1, 2] }],
        })
    })

    it('splits a single key across both groups when only some of its targets were overwritten', () => {
        const result = splitCopiedByOverwrite([{ key: 'flag-a', projectIds: [1, 2, 3], updatedProjectIds: [2] }])
        expect(result).toEqual({
            newCopies: [{ key: 'flag-a', projectIds: [1, 3] }],
            overwrites: [{ key: 'flag-a', projectIds: [2] }],
        })
    })
})
