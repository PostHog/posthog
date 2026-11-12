import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

interface ScrollToFormErrorOptions {
    /**
     * Additional CSS class selectors to search for error fields
     * @default []
     */
    extraErrorSelectors?: string[]

    /**
     * Scroll behavior
     * @default 'smooth'
     */
    behavior?: ScrollBehavior

    /**
     * Fallback error message to show if no error field is found
     */
    fallbackErrorMessage?: string
}

/**
 * Scrolls to the first error field in a form after the next animation frame to allow DOM updates.
 * Always uses 'center' alignment for consistent positioning unless the element is already
 * fully visible in the viewport.
 *
 * @param options Configuration options for the scroll behavior
 */
export function scrollToFormError(options: ScrollToFormErrorOptions = {}): void {
    const { extraErrorSelectors = [], fallbackErrorMessage } = options

    requestAnimationFrame(() => {
        const selectors = ['.Field--error', ...extraErrorSelectors]

        let errorElement: Element | null = null
        for (const selector of selectors) {
            errorElement = document.querySelector(selector)
            if (errorElement) {
                break
            }
        }

        const invalidControl = errorElement?.querySelector<HTMLElement>('[aria-invalid="true"]')
        if (invalidControl) {
            invalidControl.focus()
        } else if (errorElement) {
            // A `display: contents` field has no box to scroll to, so scroll to its message instead.
            const hasBox = errorElement.getClientRects().length > 0
            const target = (!hasBox && errorElement.querySelector('.Field__error')) || errorElement
            target.scrollIntoView({ block: 'center', behavior: 'smooth' })
        } else if (fallbackErrorMessage) {
            lemonToast.error(fallbackErrorMessage)
        }
    })
}
