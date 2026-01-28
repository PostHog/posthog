import { domToJpeg } from 'modern-screenshot'

import { toolbarConfigLogic, toolbarUploadMedia } from '~/toolbar/toolbarConfigLogic'
import { TOOLBAR_ID, elementToQuery } from '~/toolbar/utils'

export const PRODUCT_TOURS_SIDEBAR_TRANSITION_MS = 200

export interface ElementInfo {
    selector: string
    tag: string
    text: string
    ariaLabel: string | null
    attributes: Record<string, string>
    rect: { top: number; left: number; width: number; height: number }
}

export interface ElementScreenshot {
    mediaId: string
}

function screenshotFilter(node: Node): boolean {
    return !(node instanceof HTMLElement && node.id === TOOLBAR_ID)
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
        filter: screenshotFilter,
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
 * Capture a screenshot of just an element and upload it.
 * Captures full page then crops to element to preserve styles.
 * Returns the media ID for display.
 */
export async function captureAndUploadElementScreenshot(element: HTMLElement): Promise<ElementScreenshot> {
    const padding = 20
    const fillColor = '#ffffff'

    const dataUrl = await domToJpeg(document.documentElement, {
        quality: 0.9,
        scale: 1,
        backgroundColor: fillColor,
        filter: screenshotFilter,
    })

    const rect = element.getBoundingClientRect()
    const x = Math.max(0, rect.left + window.scrollX - padding)
    const y = Math.max(0, rect.top + window.scrollY - padding)
    const width = rect.width + padding * 2
    const height = rect.height + padding * 2

    const img = new Image()
    img.src = dataUrl
    await new Promise((resolve) => (img.onload = resolve))

    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) {
        throw new Error('Failed to get canvas 2d context')
    }
    ctx.fillStyle = fillColor
    ctx.fillRect(0, 0, width, height)
    ctx.drawImage(img, x, y, width, height, 0, 0, width, height)

    const blob = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob(
            (b) => {
                if (b) {
                    resolve(b)
                } else {
                    reject(new Error('Failed to create blob from canvas'))
                }
            },
            'image/jpeg',
            0.9
        )
    })
    const file = new File([blob], `tour-step-${Date.now()}.jpg`, { type: 'image/jpeg' })

    const { id } = await toolbarUploadMedia(file)
    return { mediaId: id }
}
