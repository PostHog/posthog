import { getLocalizedDateFormat } from './dateTimeUtils'

describe('getLocalizedDateFormat', () => {
    const originalNavigator = global.navigator

    afterEach(() => {
        // Restore original navigator
        Object.defineProperty(global, 'navigator', {
            value: originalNavigator,
            writable: true,
        })
    })

    it('returns US format for en-US locale', () => {
        Object.defineProperty(global, 'navigator', {
            value: { language: 'en-US' },
            writable: true,
        })
        expect(getLocalizedDateFormat()).toBe('MMM D')
    })

    it('returns US format for en-CA locale', () => {
        Object.defineProperty(global, 'navigator', {
            value: { language: 'en-CA' },
            writable: true,
        })
        expect(getLocalizedDateFormat()).toBe('MMM D')
    })

    it('returns EU format for de-DE locale', () => {
        Object.defineProperty(global, 'navigator', {
            value: { language: 'de-DE' },
            writable: true,
        })
        expect(getLocalizedDateFormat()).toBe('D MMM')
    })

    it('returns EU format for fr-FR locale', () => {
        Object.defineProperty(global, 'navigator', {
            value: { language: 'fr-FR' },
            writable: true,
        })
        expect(getLocalizedDateFormat()).toBe('D MMM')
    })

    it('falls back to US format when navigator.language is undefined', () => {
        Object.defineProperty(global, 'navigator', {
            value: { language: undefined },
            writable: true,
        })
        expect(getLocalizedDateFormat()).toBe('MMM D')
    })

    it('falls back to US format when locale detection fails', () => {
        // Mock navigator to throw an error
        Object.defineProperty(global, 'navigator', {
            value: {
                get language() {
                    throw new Error('Test error')
                },
            },
            writable: true,
        })
        expect(getLocalizedDateFormat()).toBe('MMM D')
    })
})
