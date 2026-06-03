describe('getColorVar', () => {
    let posthog: { captureException: (error: Error) => void }
    let getColorVar: (variable: string) => string
    let captureExceptionSpy: jest.SpyInstance
    let getComputedStyleSpy: jest.SpyInstance

    const mockComputedValue = (value: string): void => {
        getComputedStyleSpy.mockReturnValue({
            getPropertyValue: () => value,
        } as unknown as CSSStyleDeclaration)
    }

    beforeEach(async () => {
        // Reset modules so the module-level missing-variable Set starts empty each test.
        jest.resetModules()
        posthog = (await import('posthog-js')).default
        captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
        getComputedStyleSpy = jest.spyOn(window, 'getComputedStyle')
        ;({ getColorVar } = await import('./colors'))
    })

    afterEach(() => {
        jest.restoreAllMocks()
        document.body.removeAttribute('theme')
    })

    it('returns the trimmed CSS variable value when it resolves', () => {
        mockComputedValue('  #ff0000  ')
        expect(getColorVar('data-color-1')).toEqual('#ff0000')
        expect(captureExceptionSpy).not.toHaveBeenCalled()
    })

    it('captures a missing variable only once across repeated renders', () => {
        mockComputedValue('')

        // Simulate a chart re-rendering many times before the theme CSS is applied.
        for (let i = 0; i < 90; i++) {
            getColorVar('data-color-1')
        }

        expect(captureExceptionSpy).toHaveBeenCalledTimes(1)
        expect(captureExceptionSpy).toHaveBeenCalledWith(new Error("Couldn't find color variable --data-color-1"))
    })

    it('captures each distinct missing variable once', () => {
        mockComputedValue('')

        getColorVar('data-color-1')
        getColorVar('data-color-2')
        getColorVar('data-color-1')

        expect(captureExceptionSpy).toHaveBeenCalledTimes(2)
    })

    it.each([
        ['light', '#000'],
        ['dark', '#fff'],
    ])('falls back to %s-theme color when the variable is missing', (theme, expected) => {
        mockComputedValue('')
        document.body.setAttribute('theme', theme)
        expect(getColorVar('data-color-1')).toEqual(expected)
    })
})
