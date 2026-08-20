import { checkSelectorBreadth, checkSelectorFragility } from './selectorQuality'

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

describe('checkSelectorBreadth', () => {
    it.each([
        ['a class-only selector', '.chakra-button'],
        ['a scoped class-only selector', '.P2PDisplayModal_content .chakra-button'],
        ['a tag-only selector', 'button'],
        ['a tag and class selector', 'button.chakra-button'],
        ['a Tailwind arbitrary-value class', '.max-w-[1045px]'],
        ['a Tailwind arbitrary-value class from devtools copy', '.max-w-\\[1045px\\]'],
        ['a Tailwind arbitrary-value class with a function', '.shadow-[0_4px_6px_rgba(0,0,0,0.1)]'],
        ['a Tailwind arbitrary color class', '.text-[#fff]'],
        ['a tag-only target scoped by an ancestor id', '#checkout-panel button'],
        ['a class-only target scoped by an ancestor id', '#modal-root .chakra-button'],
        ['a tag-only target scoped by an ancestor attribute', '[id="header"] > div > button'],
    ])('flags %s as broad', (_label, selector) => {
        const result = checkSelectorBreadth(selector)
        expect(result.isBroad).toBe(true)
        expect(result.reason).not.toBeNull()
    })

    it.each([
        ['an id qualifier', '#signup-button'],
        ['a data attribute qualifier', 'button[data-attr="signup"]'],
        ['a nested id qualifier', '.modal #close'],
        ['a bare attribute qualifier', '[type="submit"]'],
        ['a class with a real attribute qualifier', '.chakra-button[data-attr="signup"]'],
        ['a bare attribute with no value', 'button[disabled]'],
    ])('does not flag %s as broad', (_label, selector) => {
        const result = checkSelectorBreadth(selector)
        expect(result.isBroad).toBe(false)
    })

    it('does not flag a position-based selector as broad (fragility check owns it)', () => {
        const result = checkSelectorBreadth('.container > button:nth-child(2)')
        expect(result.isBroad).toBe(false)
    })

    it('ignores a hash inside an attribute value', () => {
        const result = checkSelectorBreadth('a[href="#section"]')
        expect(result.isBroad).toBe(false)
    })

    it.each([[null], [undefined], ['']])('treats %p as not broad', (selector) => {
        const result = checkSelectorBreadth(selector)
        expect(result.isBroad).toBe(false)
    })
})
