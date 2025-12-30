import { domToJpeg } from 'modern-screenshot'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { TOOLBAR_ID, elementToQuery } from '~/toolbar/utils'
import { SurveyMatchType } from '~/types'

export interface ElementInfo {
    selector: string
    tag: string
    text: string
    ariaLabel: string | null
    attributes: Record<string, string>
    rect: { top: number; left: number; width: number; height: number }
}

/**
 * Capture a screenshot of the current page using modern-screenshot.
 * No user prompt required - captures DOM directly.
 * Returns base64-encoded JPEG without the data URL prefix.
 */
export async function captureScreenshot(): Promise<string> {
    const dataUrl = await domToJpeg(document.body, {
        quality: 0.7,
        scale: 0.5, // Reduce size for faster upload
        filter: (node) => {
            // Exclude the toolbar from the screenshot
            if (node instanceof HTMLElement && node.id === TOOLBAR_ID) {
                return false
            }
            return true
        },
    })
    return dataUrl.split(',')[1]
}

/**
 * Check if an element is visible on the page.
 */
function isVisible(element: Element): boolean {
    const rect = element.getBoundingClientRect()
    if (rect.width === 0 || rect.height === 0) {
        return false
    }

    const style = window.getComputedStyle(element)
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
        return false
    }

    // Check if element is in viewport
    return rect.top < window.innerHeight && rect.bottom > 0 && rect.left < window.innerWidth && rect.right > 0
}

/**
 * Check if an element is part of the toolbar.
 */
function isToolbarElement(element: Element): boolean {
    const toolbar = document.getElementById(TOOLBAR_ID)
    return toolbar?.contains(element) ?? false
}

/**
 * Generate a unique CSS selector for an element.
 * Uses the same selector generation as actions for consistency.
 */
function generateUniqueSelector(element: Element): string {
    const dataAttributes = toolbarConfigLogic.values.dataAttributes || ['data-attr']
    const selector = elementToQuery(element as HTMLElement, dataAttributes)
    return selector || element.tagName.toLowerCase()
}

/**
 * Collect all interactive elements on the page for AI analysis.
 */
export function getInteractiveElements(): ElementInfo[] {
    const selectors = 'button, a, [role="button"], input, select, textarea, [data-attr], .LemonButton'
    const elements = document.querySelectorAll(selectors)

    return Array.from(elements)
        .filter((el) => isVisible(el) && !isToolbarElement(el))
        .slice(0, 50) // Limit to avoid huge payloads
        .map((el) => {
            const rect = el.getBoundingClientRect()
            const attributes: Record<string, string> = {}

            for (const attr of ['id', 'class', 'aria-label', 'data-attr', 'placeholder', 'title', 'name', 'type']) {
                const value = el.getAttribute(attr)
                if (value) {
                    attributes[attr] = value
                }
            }

            return {
                selector: generateUniqueSelector(el),
                tag: el.tagName.toLowerCase(),
                text: el.textContent?.trim().slice(0, 100) || '',
                ariaLabel: el.getAttribute('aria-label'),
                attributes,
                rect: {
                    top: Math.round(rect.top),
                    left: Math.round(rect.left),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                },
            }
        })
}

/**
 * Get metadata about a specific element for AI context.
 */
export function getElementMetadata(element: HTMLElement): {
    selector: string
    tag: string
    text: string
    attributes: Record<string, string>
} {
    const attributes: Record<string, string> = {}

    for (const attr of ['id', 'class', 'aria-label', 'data-attr', 'placeholder', 'title', 'name']) {
        const value = element.getAttribute(attr)
        if (value) {
            attributes[attr] = value
        }
    }

    return {
        selector: generateUniqueSelector(element),
        tag: element.tagName.toLowerCase(),
        text: element.innerText?.slice(0, 200) || '',
        attributes,
    }
}

/**
 * Get basic page context for AI analysis.
 */
export function getPageContext(): { url: string; title: string } {
    return {
        url: window.location.href,
        title: document.title,
    }
}

/**
 * Get smart URL defaults for a new product tour based on the current page URL.
 *
 * Logic:
 * - If on root domain (path is "/" or empty), use "exact" match with the full URL
 * - If on a path, use "contains" match with just the pathname
 */
export function getSmartUrlDefaults(): { url: string; urlMatchType: SurveyMatchType } {
    const { pathname, origin } = window.location

    // Check if we're on the root path
    const isRootPath = pathname === '/' || pathname === ''

    if (isRootPath) {
        // For root domain, use exact match with full URL (without trailing slash for consistency)
        return {
            url: origin,
            urlMatchType: SurveyMatchType.Exact,
        }
    }
    // For paths, use contains match with the pathname
    return {
        url: pathname,
        urlMatchType: SurveyMatchType.Contains,
    }
}
