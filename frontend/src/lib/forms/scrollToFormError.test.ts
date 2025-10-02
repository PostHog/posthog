import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { scrollToFormError } from './scrollToFormError'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        error: jest.fn(),
    },
}))

describe('scrollToFormError', () => {
    let mockQuerySelector: jest.SpyInstance<Element | null, [selectors: string]>
    let mockScrollIntoView: jest.MockedFunction<(arg?: boolean | ScrollIntoViewOptions) => void>

    beforeEach(() => {
        jest.clearAllMocks()
        mockScrollIntoView = jest.fn()
        mockQuerySelector = jest.spyOn(document, 'querySelector')

        // Mock requestAnimationFrame to execute immediately
        jest.spyOn(window, 'requestAnimationFrame').mockImplementation((cb: FrameRequestCallback) => {
            cb(0)
            return 0
        })
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('scrolls to error element when found', () => {
        const mockElement = {
            scrollIntoView: mockScrollIntoView,
        } as unknown as Element
        mockQuerySelector.mockReturnValue(mockElement)

        scrollToFormError()

        expect(mockQuerySelector).toHaveBeenCalledWith('.Field--error')
        expect(mockScrollIntoView).toHaveBeenCalledWith({
            block: 'center',
            behavior: 'smooth',
        })
        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('searches extra selectors when primary selector not found', () => {
        const mockElement = {
            scrollIntoView: mockScrollIntoView,
        } as unknown as Element

        mockQuerySelector
            .mockReturnValueOnce(null) // First call for '.Field--error' returns null
            .mockReturnValueOnce(mockElement) // Second call for custom selector returns element

        scrollToFormError({
            extraErrorSelectors: ['.CohortCriteriaRow__Criteria--error'],
        })

        expect(mockQuerySelector).toHaveBeenCalledWith('.Field--error')
        expect(mockQuerySelector).toHaveBeenCalledWith('.CohortCriteriaRow__Criteria--error')
        expect(mockScrollIntoView).toHaveBeenCalledWith({
            block: 'center',
            behavior: 'smooth',
        })
        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('shows fallback toast when no error element is found', () => {
        mockQuerySelector.mockReturnValue(null)

        const fallbackMessage = 'There was an error submitting this form.'

        scrollToFormError({
            fallbackErrorMessage: fallbackMessage,
        })

        expect(mockQuerySelector).toHaveBeenCalledWith('.Field--error')
        expect(mockScrollIntoView).not.toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalledWith(fallbackMessage)
    })

    it('does not show toast when no error element is found and no fallback message provided', () => {
        mockQuerySelector.mockReturnValue(null)

        scrollToFormError()

        expect(mockQuerySelector).toHaveBeenCalledWith('.Field--error')
        expect(mockScrollIntoView).not.toHaveBeenCalled()
        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('searches all selectors including extra ones before showing fallback', () => {
        mockQuerySelector.mockReturnValue(null) // All selectors return null

        const fallbackMessage = 'No errors found anywhere.'

        scrollToFormError({
            extraErrorSelectors: ['.custom-error', '.another-error'],
            fallbackErrorMessage: fallbackMessage,
        })

        expect(mockQuerySelector).toHaveBeenCalledWith('.Field--error')
        expect(mockQuerySelector).toHaveBeenCalledWith('.custom-error')
        expect(mockQuerySelector).toHaveBeenCalledWith('.another-error')
        expect(mockScrollIntoView).not.toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalledWith(fallbackMessage)
    })
})
