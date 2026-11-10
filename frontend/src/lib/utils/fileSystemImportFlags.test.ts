import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { isFileSystemImportFlagEnabled, isFileSystemImportShown } from './fileSystemImportFlags'

const flags = (enabled: string[]): FeatureFlagsSet =>
    Object.fromEntries(enabled.map((flag) => [flag, true])) as FeatureFlagsSet

describe('fileSystemImportFlags', () => {
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

    it.each([
        { name: 'every hiding flag on', item: { hiddenWhenFlags: ['a', 'b'] }, enabled: ['a', 'b'], expected: false },
        { name: 'one hiding flag on', item: { hiddenWhenFlags: ['a', 'b'] }, enabled: ['b'], expected: true },
        {
            name: 'hiding flags on, own flag off',
            item: { flag: 'c', hiddenWhenFlags: ['a'] },
            enabled: ['a'],
            expected: false,
        },
        { name: 'no hiding flags, own flag off', item: { flag: 'c' }, enabled: [], expected: false },
    ])('shown: $name', ({ item, enabled, expected }) => {
        expect(isFileSystemImportShown(item, flags(enabled))).toBe(expected)
    })
})
