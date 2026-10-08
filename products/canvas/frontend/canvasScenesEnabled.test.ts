import { FEATURE_FLAGS } from 'lib/constants'

import { canvasScenesEnabled, spaceLinksEnabled } from './canvasScenesEnabled'

describe('canvasScenesEnabled', () => {
    it.each([
        { label: 'off without either flag', flags: {}, expected: false },
        { label: 'on in the rail navigation', flags: { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true }, expected: true },
        {
            label: 'on in the standard navigation when small software apps are on',
            flags: { [FEATURE_FLAGS.SMALL_SOFTWARE_APPS]: true },
            expected: true,
        },
        {
            label: 'on for a flag variant string',
            flags: { [FEATURE_FLAGS.SMALL_SOFTWARE_APPS]: 'test' },
            expected: true,
        },
    ])('is $label', ({ flags, expected }) => {
        expect(canvasScenesEnabled(flags)).toBe(expected)
    })

    it('links to spaces only where the Spaces scene exists', () => {
        expect(spaceLinksEnabled({ [FEATURE_FLAGS.TODAY_RAIL_NAV]: true })).toBe(true)
        expect(spaceLinksEnabled({ [FEATURE_FLAGS.SMALL_SOFTWARE_APPS]: true })).toBe(false)
        expect(spaceLinksEnabled({})).toBe(false)
    })
})
