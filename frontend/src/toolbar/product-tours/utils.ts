import { domToJpeg } from 'modern-screenshot'

import { TOOLBAR_ID } from '~/toolbar/utils'

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
 */
function generateUniqueSelector(element: Element): string {
    // Try data-attr first (PostHog convention)
    const dataAttr = element.getAttribute('data-attr')
    if (dataAttr) {
        return `[data-attr="${dataAttr}"]`
    }

    // Try ID
    if (element.id) {
        return `#${element.id}`
    }

    // Try unique class combination
    if (element.classList.length > 0) {
        const classes = Array.from(element.classList).slice(0, 3).join('.')
        const selector = `${element.tagName.toLowerCase()}.${classes}`
        if (document.querySelectorAll(selector).length === 1) {
            return selector
        }
    }

    // Build path from parent
    const path: string[] = []
    let current: Element | null = element

    while (current && current !== document.body) {
        let selector = current.tagName.toLowerCase()

        if (current.id) {
            selector = `#${current.id}`
            path.unshift(selector)
            break
        }

        const parent: Element | null = current.parentElement
        if (parent) {
            const siblings = Array.from(parent.children).filter((c: Element) => c.tagName === current!.tagName)
            if (siblings.length > 1) {
                const index = siblings.indexOf(current) + 1
                selector += `:nth-of-type(${index})`
            }
        }

        path.unshift(selector)
        current = parent
    }

    return path.join(' > ')
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
