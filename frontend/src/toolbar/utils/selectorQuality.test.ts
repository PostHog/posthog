import { checkSelectorFragility } from './selectorQuality'

describe('checkSelectorFragility', () => {
    describe('fragile selectors', () => {
        it('flags nth-of-type as fragile', () => {
            const result = checkSelectorFragility('.toolbar > button:nth-of-type(4)')
            expect(result.isFragile).toBe(true)
            expect(result.fragileSelector).toBe(':nth-of-type(4)')
        })

        it('flags nth-child as fragile', () => {
            const result = checkSelectorFragility('.container > div:nth-child(2)')
            expect(result.isFragile).toBe(true)
            expect(result.fragileSelector).toBe(':nth-child(2)')
        })

        it('handles null selector as not fragile (no warning before selection)', () => {
            const result = checkSelectorFragility(null)
            expect(result.isFragile).toBe(false)
        })

        it('handles empty string as not fragile', () => {
            const result = checkSelectorFragility('')
            expect(result.isFragile).toBe(false)
        })

        it('handles undefined as not fragile', () => {
            const result = checkSelectorFragility(undefined)
            expect(result.isFragile).toBe(false)
        })
    })

    describe('non-fragile selectors', () => {
        it('accepts data-posthog attribute', () => {
            const result = checkSelectorFragility('[data-posthog="export-button"]')
            expect(result.isFragile).toBe(false)
            expect(result.fragileSelector).toBeNull()
        })

        it('accepts id selector', () => {
            const result = checkSelectorFragility('#export-button')
            expect(result.isFragile).toBe(false)
        })

        it('accepts class selector', () => {
            const result = checkSelectorFragility('.export-button')
            expect(result.isFragile).toBe(false)
        })

        it('accepts nested class selectors without nth', () => {
            const result = checkSelectorFragility('.container > .row > .button')
            expect(result.isFragile).toBe(false)
        })
    })
})
