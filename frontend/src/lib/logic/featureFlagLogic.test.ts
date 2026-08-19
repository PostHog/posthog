import { areClientFeatureFlagsHonored } from './featureFlagLogic'

describe('areClientFeatureFlagsHonored', () => {
    it.each([
        [null, false],
        [{ cloud: false, is_debug: false }, false],
        [{ cloud: true, is_debug: false }, true],
        [{ cloud: false, is_debug: true }, true],
        [{ cloud: true, is_debug: true }, true],
    ])('preflight %s returns %s', (preflight, expected) => {
        expect(areClientFeatureFlagsHonored(preflight)).toBe(expected)
    })
})
