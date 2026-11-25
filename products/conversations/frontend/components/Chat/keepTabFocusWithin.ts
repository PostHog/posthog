const TABBABLE_SELECTOR = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled]):not([type="hidden"])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[contenteditable="true"]',
    '[tabindex]',
].join(',')

/** Wraps Tab from the last tabbable element to the first, and Shift+Tab from the first to the last. */
export function keepTabFocusWithin(
    container: HTMLElement,
    event: Pick<KeyboardEvent, 'shiftKey' | 'preventDefault'>
): void {
    const tabbables = Array.from(container.querySelectorAll<HTMLElement>(TABBABLE_SELECTOR)).filter(
        (el) => el.tabIndex >= 0 && (typeof el.checkVisibility !== 'function' || el.checkVisibility())
    )
    if (tabbables.length === 0) {
        return
    }
    const first = tabbables[0]
    const last = tabbables[tabbables.length - 1]
    const active = document.activeElement
    if (event.shiftKey ? active === first : active === last) {
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
    }
}
