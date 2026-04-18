import { blastRadiusCountLabel } from './blastRadiusCountLabel'

describe('blastRadiusCountLabel', () => {
    it.each([
        [null, 'organizations', 'person profiles'],
        [undefined, 'organizations', 'person profiles'],
        [0, 'organizations', 'organizations'],
        [1, 'accounts', 'accounts'],
        [2, 'workspaces', 'workspaces'],
    ])('groupTypeIndex=%p with fallback=%p resolves to "%s"', (groupTypeIndex, fallback, expected) => {
        expect(blastRadiusCountLabel(groupTypeIndex, fallback)).toBe(expected)
    })
})
