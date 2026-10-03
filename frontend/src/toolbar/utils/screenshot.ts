import { captureElementImage } from 'lib/utils/captureElementImage'

import { toolbarUploadMedia } from '~/toolbar/toolbarFetch'
import { TOOLBAR_ID, toError } from '~/toolbar/utils'

export interface ElementScreenshot {
    mediaId: string
}

function screenshotFilter(node: Node): boolean {
    return !(node instanceof HTMLElement && node.id === TOOLBAR_ID)
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
            ...options,
        })
    } catch (error) {
        // html-to-image rejects with a raw DOM Event when a resource on the page fails to load.
        // Rethrow a real Error so the failure reaches error tracking with a message and a stack.
        throw toError(error, `Failed to capture screenshot of ${describeElement(element)}`)
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
