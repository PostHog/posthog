import { finder } from '@medv/finder'
import { querySelectorAllDeep } from 'query-selector-shadow-dom'

import { CLICK_TARGETS, CLICK_TARGET_SELECTOR, TAGS_TO_IGNORE } from 'lib/actionUtils'
import { cssEscape } from 'lib/utils/cssEscape'

import { toolbarLogger } from '~/toolbar/core/toolbarLogger'
import { captureToolbarException } from '~/toolbar/core/toolbarPosthogJS'

export const TOOLBAR_ID = '__POSTHOG_TOOLBAR__'

const elementToQueryCache = new WeakMap<HTMLElement, string | undefined>()
export const TOOLBAR_CONTAINER_CLASS = 'toolbar-global-fade-container'

export function getToolbarRootElement(): HTMLElement | null {
    return window.document.getElementById(TOOLBAR_ID) || null
}

export function hasCursorPointer(element: HTMLElement): boolean {
    return window.getComputedStyle(element)?.getPropertyValue('cursor') === 'pointer'
}

export function getParent(element: HTMLElement): HTMLElement | null {
    const parent = element.parentNode
    // 11 = DOCUMENT_FRAGMENT_NODE
    if (parent?.nodeType === window.Node.DOCUMENT_FRAGMENT_NODE) {
        return (parent as ShadowRoot).host as HTMLElement
    }
    if (parent?.nodeType === window.Node.ELEMENT_NODE) {
        return parent as HTMLElement
    }
    return null
}

export function isParentOf(element: HTMLElement, possibleParent: HTMLElement): boolean {
    let loopElement = element as HTMLElement | null
    while (loopElement) {
        if (loopElement !== element && loopElement === possibleParent) {
            return true
        }
        loopElement = getParent(loopElement)
    }

    return false
}

export function trimElement(
    element: HTMLElement,
    options?: { selector?: string; cursorPointerCache?: WeakMap<HTMLElement, boolean> }
): HTMLElement | null {
    const target_selector = options?.selector || CLICK_TARGET_SELECTOR
    const cursorPointerCache = options?.cursorPointerCache
    if (!element) {
        return null
    }
    const rootElement = getToolbarRootElement()
    if (rootElement && isParentOf(element, rootElement)) {
        return null
    }

    let loopElement = element

    while (true) {
        if (loopElement.children.length === 1) {
            loopElement = loopElement.children[0] as HTMLElement
        } else {
            break
        }
    }

    const hasCachedPointer = (el: HTMLElement): boolean => {
        if (!cursorPointerCache) {
            return window.getComputedStyle(el).getPropertyValue('cursor') === 'pointer'
        }
        const cached = cursorPointerCache.get(el)
        if (cached !== undefined) {
            return cached
        }
        const result = window.getComputedStyle(el).getPropertyValue('cursor') === 'pointer'
        cursorPointerCache.set(el, result)
        return result
    }

    while (loopElement) {
        const parent = getParent(loopElement)
        if (!parent) {
            return null
        }

        if (loopElement.matches?.(target_selector)) {
            return loopElement
        }

        if (hasCachedPointer(loopElement) && !hasCachedPointer(parent)) {
            return loopElement
        }

        loopElement = parent
    }

    return null
}

export function elementIsVisible(element: HTMLElement, cache: WeakMap<HTMLElement, boolean>): boolean {
    try {
        const alreadyCached = cache.get(element)
        if (alreadyCached !== undefined) {
            return alreadyCached
        }

        if (element.checkVisibility) {
            const nativeIsVisible = element.checkVisibility({
                checkOpacity: true,
                checkVisibilityCSS: true,
            })
            cache.set(element, nativeIsVisible)
            return nativeIsVisible
        }

        const style = window.getComputedStyle(element)
        const isInvisible = style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0
        if (isInvisible) {
            cache.set(element, false)
            return false
        }

        // Check parent chain for display/visibility
        let parent = element.parentElement
        while (parent) {
            // Check cache first
            const cached = cache.get(parent)
            if (cached !== undefined) {
                if (!cached) {
                    return false
                }
                // If cached as visible, skip to next parent
                parent = parent.parentElement
                continue
            }

            const parentStyle = window.getComputedStyle(parent)
            const parentVisible = parentStyle.display !== 'none' && parentStyle.visibility !== 'hidden'

            cache.set(parent, parentVisible)

            if (!parentVisible) {
                return false
            }
            parent = parent.parentElement
        }

        // Check if element has actual rendered dimensions
        const rect = element.getBoundingClientRect()
        const elementHasActualRenderedDimensions =
            rect.width > 0 ||
            rect.height > 0 ||
            // Some elements might be 0x0 but still visible (e.g., inline elements with content)
            element.getClientRects().length > 0
        cache.set(element, elementHasActualRenderedDimensions)
        return elementHasActualRenderedDimensions
    } catch {
        // if we can't get the computed style, we'll assume the element is visible
        return true
    }
}

export function getAllClickTargets(
    startNode: Document | HTMLElement | ShadowRoot = document,
    selector?: string
): HTMLElement[] {
    const targetSelector = selector || CLICK_TARGET_SELECTOR
    const elements = startNode.querySelectorAll(targetSelector) as unknown as HTMLElement[]

    const allElements = [...(startNode.querySelectorAll('*') as unknown as HTMLElement[])]

    // loop through all elements and getComputedStyle
    const pointerElements = allElements.filter((el) => {
        if (CLICK_TARGETS.indexOf(el.tagName.toLowerCase()) >= 0) {
            return false
        }
        const compStyles = window.getComputedStyle(el)
        return compStyles.getPropertyValue('cursor') === 'pointer'
    })

    const shadowElements = allElements
        .filter((el) => el.shadowRoot && el.getAttribute('id') !== TOOLBAR_ID)
        .map((el: HTMLElement) => (el.shadowRoot ? getAllClickTargets(el.shadowRoot, targetSelector) : []))
        .reduce((a, b) => {
            a.push(...b)
            return a
        }, [] as HTMLElement[])
    const selectedElements = [...elements, ...pointerElements, ...shadowElements]
        .map((e) => trimElement(e, { selector: targetSelector }))
        .filter((e) => e)
    const uniqueElements = Array.from(new Set(selectedElements)) as HTMLElement[]

    const visibilityCache = new WeakMap<HTMLElement, boolean>()
    return uniqueElements.filter((el) => elementIsVisible(el, visibilityCache))
}

export function getSafeText(el: HTMLElement): string {
    if (!el.childNodes || !el.childNodes.length) {
        return ''
    }
    let elText = ''
    el.childNodes.forEach((child) => {
        if (child.nodeType !== 3 || !child.textContent) {
            return
        }
        elText += child.textContent
            .trim()
            .replace(/[\r\n]/g, ' ')
            .replace(/[ ]+/g, ' ') // normalize whitespace
            .substring(0, 255)
    })
    return elText
}

export function elementToQuery(element: HTMLElement, dataAttributes: string[]): string | undefined {
    if (!element) {
        return
    }

    if (elementToQueryCache.has(element)) {
        return elementToQueryCache.get(element)
    }

    const result = computeElementQuery(element, dataAttributes)
    elementToQueryCache.set(element, result)
    return result
}

function computeElementQuery(element: HTMLElement, dataAttributes: string[]): string | undefined {
    for (const { name, value } of Array.from(element.attributes)) {
        if (!dataAttributes.includes(name)) {
            continue
        }

        const escapedSelector = `[${cssEscape(name)}="${cssEscape(value)}"]`
        const unescapedSelector = `[${name}="${value}"]`

        if (querySelectorAllDeep(escapedSelector).length == 1) {
            // if we return the _valid_ escaped CSS,
            // the action matching in PostHog might not match it
            // because it's not really CSS matching
            return unescapedSelector
        }
    }

    try {
        const foundSelector = finder(element, {
            tagName: (name) => !TAGS_TO_IGNORE.includes(name),
            // include several selectors e.g. prefer .project-homepage > .project-header > .project-title over .project-title
            seedMinLength: 5,
            attr: (name) => {
                // preference to data attributes if they exist
                // that aren't in the PostHog preferred list - they were returned early above
                return name.startsWith('data-')
            },
        })
        return slashDotDataAttrUnescape(foundSelector)
    } catch (error) {
        toolbarLogger.warn('element_selector', 'Error while trying to find a selector for element')
        captureToolbarException(error, 'element_selector_computation')
        return undefined
    }
}

/*
 * KLUDGE: e.g. [data-attr="session\.recording\.preview"] is valid CSS
 * but our action matching doesn't support it
 * in order to avoid trying to write a general purpose CSS unescaper
 * we just remove the backslash in this specific pattern
 * if it matches data-attr="bla\.blah\.blah"
 */
export function slashDotDataAttrUnescape(foundSelector: string): string | undefined {
    return foundSelector.replace(/\\./g, '.')
}
