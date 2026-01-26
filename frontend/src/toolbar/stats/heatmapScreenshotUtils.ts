import { domToJpeg } from 'modern-screenshot'

import { TOOLBAR_ID } from '~/toolbar/utils'

/**
 * Filter function to exclude toolbar elements from screenshots.
 */
function screenshotFilter(node: Node): boolean {
    return !(node instanceof HTMLElement && node.id === TOOLBAR_ID)
}

/**
 * Capture a full-page screenshot for heatmap display.
 * Returns a File object ready for upload via toolbarUploadMedia.
 */
export async function captureHeatmapScreenshot(): Promise<File> {
    const dataUrl = await domToJpeg(document.documentElement, {
        quality: 0.7,
        scale: 1,
        filter: screenshotFilter,
    })

    // Convert data URL to Blob
    const response = await fetch(dataUrl)
    const blob = await response.blob()

    // Create File from Blob with timestamp filename
    return new File([blob], `heatmap-screenshot-${Date.now()}.jpg`, { type: 'image/jpeg' })
}

/**
 * Get the current page URL for heatmap data pattern.
 */
export function getCurrentPageUrl(): string {
    return window.location.href
}

/**
 * Get a suggested data URL pattern based on current URL.
 * Replaces numeric path segments with wildcards.
 */
export function getSuggestedDataUrlPattern(): string {
    const url = new URL(window.location.href)
    // Replace numeric path segments with wildcards (e.g., /users/123 -> /users/*)
    const pathWithWildcards = url.pathname.replace(/\/\d+/g, '/*')
    return `${url.origin}${pathWithWildcards}`
}
