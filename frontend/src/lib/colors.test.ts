import posthog from 'posthog-js'

import { getColorVar } from './colors'

describe('getColorVar', () => {
    let captureExceptionSpy: jest.SpyInstance
    let getComputedStyleSpy: jest.SpyInstance

    const mockComputedValue = (value: string): void => {
        getComputedStyleSpy.mockReturnValue({
            getPropertyValue: () => value,
        } as unknown as CSSStyleDeclaration)
    }

    beforeEach(() => {
        captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
        getComputedStyleSpy = jest.spyOn(window, 'getComputedStyle')
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('returns the trimmed CSS variable value when it resolves', () => {
        mockComputedValue('  #ff0000  ')
        expect(getColorVar('data-color-resolved')).toEqual('#ff0000')
        expect(captureExceptionSpy).not.toHaveBeenCalled()
    })

    it('captures a missing variable only once across repeated renders', () => {
        mockComputedValue('')

        // Simulate a chart re-rendering many times before the theme CSS is applied.
        for (let i = 0; i < 90; i++) {
            getColorVar('data-color-burst')
        }

        expect(captureExceptionSpy).toHaveBeenCalledTimes(1)
        expect(captureExceptionSpy).toHaveBeenCalledWith(new Error("Couldn't find color variable --data-color-burst"))
    })

    it('falls back to a theme-appropriate color when the variable is missing', () => {
        mockComputedValue('')

        document.body.setAttribute('theme', 'light')
        expect(getColorVar('data-color-light-fallback')).toEqual('#000')

        document.body.setAttribute('theme', 'dark')
        expect(getColorVar('data-color-dark-fallback')).toEqual('#fff')

        document.body.removeAttribute('theme')
    })
})
