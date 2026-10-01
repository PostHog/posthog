import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { isFileSystemImportFlagEnabled } from './fileSystemImportFlags'

describe('isFileSystemImportFlagEnabled', () => {
    const flags = (enabled: string[]): FeatureFlagsSet =>
        Object.fromEntries(enabled.map((flag) => [flag, true])) as FeatureFlagsSet

    it.each([
        { name: 'no flag', item: {}, enabled: [], expected: true },
        { name: 'flag on', item: { flag: 'a' }, enabled: ['a'], expected: true },
        { name: 'flag off', item: { flag: 'a' }, enabled: [], expected: false },
        {
            name: 'flag off, alternative on',
            item: { flag: 'a', alternativeFlags: ['b'] },
            enabled: ['b'],
            expected: true,
        },
        {
            name: 'flag and alternatives off',
            item: { flag: 'a', alternativeFlags: ['b', 'c'] },
            enabled: ['d'],
            expected: false,
        },
    ])('$name', ({ item, enabled, expected }) => {
        expect(isFileSystemImportFlagEnabled(item, flags(enabled))).toBe(expected)
    })
})
