function isFocusable(element: HTMLElement): boolean {
    if (element.tagName === 'DIV' || element.tagName === 'SECTION') {
        return false
    }
    const hasTabIndex = element.hasAttribute('tabindex')
    const tabIndex = hasTabIndex ? parseInt(element.getAttribute('tabindex') || '0', 10) : -1
    const isFocusableInherently =
        /^(input|select|textarea|button|object)$/.test(element.tagName.toLowerCase()) ||
        (element.tagName.toLowerCase() === 'a' && element.hasAttribute('href'))
    const isDisabledOrHidden =
        element.hasAttribute('disabled') ||
        element.getAttribute('aria-hidden') === 'true' ||
        element.style.display === 'none' ||
        element.style.visibility === 'hidden'

    return !isDisabledOrHidden && (isFocusableInherently || tabIndex >= 0)
}

export function findNextFocusableElement(startElement: HTMLElement): HTMLElement | null {
    function searchFocusable(currentElement: HTMLElement): HTMLElement | null {
        if (isFocusable(currentElement) && currentElement !== startElement) {
            return currentElement
        }

        let child = currentElement.firstElementChild as HTMLElement
        while (child) {
            const focusable = searchFocusable(child)
            if (focusable) {
                return focusable
            }
            child = child.nextElementSibling as HTMLElement
        }

        return null
    }

    let nextSearchable = startElement.nextElementSibling as HTMLElement | null
    let parentElement = startElement.parentElement

    while (parentElement) {
        while (nextSearchable) {
            const focusable = searchFocusable(nextSearchable)
            if (focusable) {
                return focusable
            }
            nextSearchable = nextSearchable.nextElementSibling as HTMLElement
        }

        nextSearchable = parentElement.nextElementSibling as HTMLElement | null
        parentElement = parentElement.parentElement
    }

    return null
}

export function findPreviousFocusableElement(startElement: HTMLElement): HTMLElement | null {
    function searchFocusable(currentElement: HTMLElement): HTMLElement | null {
        if (isFocusable(currentElement) && currentElement !== startElement) {
            return currentElement
        }

        let child = currentElement.lastElementChild as HTMLElement
        while (child) {
            const focusable = searchFocusable(child)
            if (focusable) {
                return focusable
            }
            child = child.previousElementSibling as HTMLElement
        }

        return null
    }

    let prevSearchable = startElement.previousElementSibling as HTMLElement | null
    let parentElement = startElement.parentElement

    while (parentElement) {
        while (prevSearchable) {
            const focusable = searchFocusable(prevSearchable)
            if (focusable) {
                return focusable
            }
            prevSearchable = prevSearchable.previousElementSibling as HTMLElement
        }

        if (isFocusable(parentElement) && parentElement !== startElement) {
            return parentElement
        }

        prevSearchable = parentElement.previousElementSibling as HTMLElement | null
        parentElement = parentElement.parentElement
    }

    return null
}
