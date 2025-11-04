import { analyzeSelectorQuality, generateSuggestedAttribute } from './selectorQuality'

describe('analyzeSelectorQuality', () => {
    describe('good quality selectors', () => {
        it('rates data-posthog attribute as good', () => {
            const result = analyzeSelectorQuality('[data-posthog="export-button"]')
            expect(result.quality).toBe('good')
            expect(result.issues).toHaveLength(0)
        })

        it('rates id attribute as good', () => {
            const result = analyzeSelectorQuality('#export-button')
            expect(result.quality).toBe('good')
            expect(result.issues).toHaveLength(0)
        })

        it('rates data-testid attribute as good', () => {
            const result = analyzeSelectorQuality('[data-testid="export-button"]')
            expect(result.quality).toBe('good')
            expect(result.issues).toHaveLength(0)
        })
    })

    describe('position-based selectors (fragile)', () => {
        it('flags nth-of-type as fragile', () => {
            const result = analyzeSelectorQuality('.toolbar > button:nth-of-type(4)')
            expect(result.quality).toBe('fragile')
            expect(result.issues).toContainEqual(
                expect.objectContaining({
                    type: 'position',
                    severity: 'error',
                })
            )
            expect(result.recommendations).toContain(
                'Add a data-posthog attribute to your element for stable identification'
            )
        })

        it('flags nth-child as fragile', () => {
            const result = analyzeSelectorQuality('.container > div:nth-child(2)')
            expect(result.quality).toBe('fragile')
            expect(result.issues).toContainEqual(
                expect.objectContaining({
                    type: 'position',
                    severity: 'error',
                })
            )
        })

        it('flags first-child and last-child as warning', () => {
            const result = analyzeSelectorQuality('.nav > a:first-child')
            expect(result.issues).toContainEqual(
                expect.objectContaining({
                    type: 'position',
                    severity: 'warning',
                })
            )
        })
    })

    describe('selector depth', () => {
        it('flags very deep selectors as warning', () => {
            const result = analyzeSelectorQuality('.a > .b > .c > .d > .e > .f')
            // Deep selectors get warning level unless combined with position selectors
            expect(result.quality).toBe('warning')
            expect(result.issues).toContainEqual(
                expect.objectContaining({
                    type: 'depth',
                    severity: 'error',
                })
            )
        })

        it('flags moderately deep selectors as warning', () => {
            const result = analyzeSelectorQuality('.a > .b > .c')
            expect(result.quality).toBe('warning')
            expect(result.issues).toContainEqual(
                expect.objectContaining({
                    type: 'depth',
                    severity: 'warning',
                })
            )
        })

        it('accepts shallow selectors', () => {
            const result = analyzeSelectorQuality('.button-class')
            expect(result.issues.filter((i) => i.type === 'depth')).toHaveLength(0)
        })
    })

    describe('generic element selectors', () => {
        it('flags bare element selectors as warning', () => {
            const result = analyzeSelectorQuality('button > span')
            expect(result.issues).toContainEqual(
                expect.objectContaining({
                    type: 'generic',
                    severity: 'warning',
                })
            )
        })

        it('accepts element selectors with unique attributes', () => {
            const result = analyzeSelectorQuality('[data-posthog="test"] > span')
            expect(result.quality).toBe('good')
        })
    })

    describe('attribute selectors with numbers', () => {
        it('flags attributes with long numbers as warning', () => {
            const result = analyzeSelectorQuality('[data-id="user-12345678"]')
            expect(result.issues).toContainEqual(
                expect.objectContaining({
                    type: 'attribute-with-numbers',
                    severity: 'warning',
                })
            )
        })

        it('accepts attributes with short numbers', () => {
            const result = analyzeSelectorQuality('[data-index="1"]')
            expect(result.issues.filter((i) => i.type === 'attribute-with-numbers')).toHaveLength(0)
        })
    })

    describe('complex pseudo-selectors', () => {
        it('flags :not() as complex', () => {
            const result = analyzeSelectorQuality('.button:not(.disabled)')
            expect(result.issues).toContainEqual(
                expect.objectContaining({
                    type: 'complex',
                    severity: 'warning',
                })
            )
        })

        it('flags wildcard selectors', () => {
            const result = analyzeSelectorQuality('.container > * > button')
            expect(result.issues).toContainEqual(
                expect.objectContaining({
                    type: 'complex',
                    severity: 'warning',
                })
            )
        })
    })

    describe('empty or null selectors', () => {
        it('handles null selector as fragile', () => {
            const result = analyzeSelectorQuality(null)
            expect(result.quality).toBe('fragile')
            expect(result.recommendations[0]).toContain('data-posthog')
        })

        it('handles empty string as fragile', () => {
            const result = analyzeSelectorQuality('')
            expect(result.quality).toBe('fragile')
        })

        it('handles undefined as fragile', () => {
            const result = analyzeSelectorQuality(undefined)
            expect(result.quality).toBe('fragile')
        })
    })

    describe('combined issues', () => {
        it('rates selector with multiple issues as fragile', () => {
            const result = analyzeSelectorQuality('div > button:nth-of-type(4) > span > a > .text')
            expect(result.quality).toBe('fragile')
            expect(result.issues.length).toBeGreaterThan(1)
        })
    })

    describe('real-world examples', () => {
        it('handles PostHog toolbar selector (from customer ticket)', () => {
            const result = analyzeSelectorQuality('.flex-align-center > button:nth-of-type(4)')
            expect(result.quality).toBe('fragile')
            expect(result.issues).toContainEqual(
                expect.objectContaining({
                    type: 'position',
                })
            )
        })

        it('accepts good class-based selector', () => {
            const result = analyzeSelectorQuality('.export-excel-button')
            expect(result.quality).toBe('good')
        })

        it('accepts attribute selector with data attribute', () => {
            const result = analyzeSelectorQuality('button[data-action="export"]')
            expect(result.quality).toBe('good')
        })
    })
})

describe('generateSuggestedAttribute', () => {
    it('generates attribute from element text content', () => {
        const element = document.createElement('button')
        element.textContent = 'Export Excel'
        const result = generateSuggestedAttribute(element)
        expect(result).toBe('export-excel')
    })

    it('generates attribute from aria-label', () => {
        const element = document.createElement('button')
        element.setAttribute('aria-label', 'Close Dialog')
        const result = generateSuggestedAttribute(element)
        expect(result).toBe('close-dialog')
    })

    it('generates attribute from name attribute', () => {
        const element = document.createElement('input')
        element.setAttribute('name', 'email')
        const result = generateSuggestedAttribute(element)
        expect(result).toBe('email')
    })

    it('generates attribute from tag name and class', () => {
        const element = document.createElement('button')
        element.className = 'primary-action secondary'
        const result = generateSuggestedAttribute(element)
        expect(result).toBe('button-primary-action')
    })

    it('falls back to tag name', () => {
        const element = document.createElement('button')
        const result = generateSuggestedAttribute(element)
        expect(result).toBe('button-element')
    })

    it('truncates long text to 30 characters', () => {
        const element = document.createElement('button')
        element.textContent = 'This is a very long button text that should be truncated'
        const result = generateSuggestedAttribute(element)
        expect(result.length).toBeLessThanOrEqual(30)
    })

    it('removes special characters', () => {
        const element = document.createElement('button')
        element.textContent = 'Sign Up! (Free)'
        const result = generateSuggestedAttribute(element)
        expect(result).toBe('sign-up-free')
    })
})
