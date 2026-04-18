import { PERSON_PROFILES_COUNT_LABEL, blastRadiusCountLabel } from './blastRadiusCountLabel'

describe('blastRadiusCountLabel', () => {
    it.each([
        [null, 'person profiles'],
        [undefined, 'person profiles'],
    ])('returns "person profiles" for user-level aggregation (%p)', (groupTypeIndex, expected) => {
        expect(blastRadiusCountLabel(groupTypeIndex, 'organizations')).toBe(expected)
    })

    it.each([
        [0, 'organizations'],
        [1, 'accounts'],
        [2, 'workspaces'],
    ])('returns the group label fallback for group_type_index %p', (groupTypeIndex, fallback) => {
        expect(blastRadiusCountLabel(groupTypeIndex, fallback)).toBe(fallback)
    })

    it('exports the canonical user-aggregation label', () => {
        expect(PERSON_PROFILES_COUNT_LABEL).toBe('person profiles')
    })
})
