import { EmptyImageError, captureElementImage } from 'lib/utils/captureElementImage'

import { toolbarUploadMedia } from '~/toolbar/shared/toolbarFetch'
import { isToolbarRootElement, toError } from '~/toolbar/shared/utils'

export interface ElementScreenshot {
    mediaId: string
}

function screenshotFilter(node: Node): boolean {
    return !(node instanceof HTMLElement && isToolbarRootElement(node))
}

export interface CaptureOptions {
    pixelRatio?: number
    width?: number
    height?: number
    backgroundColor?: string
}

function describeElement(element: HTMLElement): string {
    return `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ''}`
}

export async function captureElementScreenshot(element: HTMLElement, options?: CaptureOptions): Promise<Blob> {
    try {
        return await captureElementImage(element, {
            type: 'image/jpeg',
            quality: 0.7,
            filter: screenshotFilter,
            backgroundColor: '#ffffff',
            ...options,
        })
    } catch (error) {
        // html-to-image rejects with a raw DOM Event when a resource on the page fails to load.
        // Rethrow a real Error so the failure reaches error tracking with a message and a stack.
        const context = `Failed to capture screenshot of ${describeElement(element)}`
        if (error instanceof EmptyImageError) {
            throw error
        }
        if (!(error instanceof Error)) {
            throw toError(error, context)
        }
        // Its own errors can quote the page's URLs, such as an SVG `<use>` href that carries a signed token.
        // The new Error keeps only the original type, so neither its message nor its stack carries page content.
        throw new Error(`${context} (threw ${error.name})`)
    }
}

export async function uploadScreenshot(blob: Blob): Promise<ElementScreenshot> {
    const file = new File([blob], `screenshot-${Date.now()}.jpg`, { type: 'image/jpeg' })
    const { id } = await toolbarUploadMedia(file)
    return { mediaId: id }
}

export async function captureAndUploadElementScreenshot(element: HTMLElement): Promise<ElementScreenshot> {
    const blob = await captureElementScreenshot(element)
    return uploadScreenshot(blob)
}
