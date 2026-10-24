import { FeatureFlagBasicType } from '~/types'

import { flagSelectorButtonLabel, pickedFeatureFlag } from './FlagSelector'

describe('FlagSelector', () => {
    describe('flagSelectorButtonLabel', () => {
        const PICK = { id: 7, label: 'checkout-redesign' }

        test.each([
            ['resolved key wins over a pick', 'foo', 7, PICK, 'Fallback', 'foo'],
            ['pick stands in while the key is still loading', '', 7, PICK, 'Fallback', PICK.label],
            ['pick stands in when the key lookup fails', '', 7, { id: 7, label: 'foo' }, 'Fallback', 'foo'],
            ['pick the caller never stored is dropped', '', undefined, PICK, 'Fallback', 'Fallback'],
            ['pick for a different flag is dropped', '', 9, PICK, 'Fallback', 'Fallback'],
            ['falls back to the initial label with nothing picked', '', undefined, undefined, 'Fallback', 'Fallback'],
            ['falls back to the default with no initial label', '', undefined, undefined, undefined, 'Select flag'],
        ])(
            '%s',
            (
                _name: string,
                flagKey: string,
                value: number | undefined,
                pickedFlag: { id: number; label: string } | undefined,
                initialButtonLabel: string | undefined,
                expected: string
            ) => {
                expect(flagSelectorButtonLabel({ flagKey, value, pickedFlag, initialButtonLabel })).toBe(expected)
            }
        )
    })

    describe('pickedFeatureFlag', () => {
        const FULL_FLAG = {
            id: 7,
            key: 'checkout-redesign',
            name: '',
            active: true,
            filters: { groups: [] },
        } as unknown as FeatureFlagBasicType

        it('hands back the whole flag when the row is one', () => {
            expect(pickedFeatureFlag(FULL_FLAG, 7)).toEqual({ id: 7, key: 'checkout-redesign', flag: FULL_FLAG })
        })

        // A Recent row holds only what labels it. Returning it as `flag` is what let callers store a
        // feature flag with no key and no targeting config, which the replay trigger and the survey
        // variant selector both read.
        it('withholds the flag when the row is a stored summary', () => {
            expect(pickedFeatureFlag({ name: '', id: 7, key: 'checkout-redesign' }, 7)).toEqual({
                id: 7,
                key: 'checkout-redesign',
                flag: undefined,
            })
        })

        it('takes the id from the picked value when the row carries none', () => {
            expect(pickedFeatureFlag({ key: 'checkout-redesign' }, 7)?.id).toBe(7)
        })

        it.each([
            ['a row with no key', { name: '', id: 7 }, 7],
            ['a row with an empty key', { name: '', id: 7, key: '' }, 7],
            ['a row with no resolvable id', { key: 'checkout-redesign' }, null],
        ])('is not a selection: %s', (_name: string, item: Record<string, unknown>, value: number | null) => {
            expect(pickedFeatureFlag(item, value)).toBeNull()
        })
    })
})
