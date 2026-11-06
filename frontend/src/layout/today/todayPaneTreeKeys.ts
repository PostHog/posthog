/** Marks a section heading, so the arrow keys can open and close it like a tree node. */
export const SECTION_TOGGLE_ATTR = 'data-pane-section-toggle'

/**
 * Tree keys for a pane's search list. Right opens a closed heading and Left closes an open one. Left on a row inside an open
 * section closes that section. Returns the heading that should take focus, or null when the key was not used.
 */
export function toggleSectionWithArrow(element: Element | null | undefined, key: string): HTMLElement | null {
    if (!(element instanceof HTMLElement)) {
        return null
    }
    const isHeading = element.hasAttribute(SECTION_TOGGLE_ATTR)
    const heading = isHeading
        ? element
        : key === 'ArrowLeft'
          ? element.closest('section')?.querySelector<HTMLElement>(`[${SECTION_TOGGLE_ATTR}]`)
          : null
    if (!heading) {
        return null
    }
    const expanded = heading.getAttribute('aria-expanded') === 'true'
    if ((key === 'ArrowRight' && isHeading && !expanded) || (key === 'ArrowLeft' && expanded)) {
        heading.click()
        return heading
    }
    return null
}

/**
 * Moves the list highlight to an option while focus stays in the search field. base-ui's Autocomplete has no prop or
 * action that sets the highlight, so this does what a pointer over the option does. Check for one when base-ui updates.
 */
export function highlightOption(option: HTMLElement): void {
    option.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerType: 'mouse' }))
    option.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }))
}
