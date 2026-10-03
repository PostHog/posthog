import { canTrimProperty } from './person-property-utils'

describe('canTrimProperty', () => {
    it('protects SDK-derived campaign person properties', () => {
        expect(canTrimProperty('$fbc')).toBe(false)
        expect(canTrimProperty('custom_property')).toBe(true)
    })
})
