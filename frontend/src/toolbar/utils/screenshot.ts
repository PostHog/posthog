import { captureElementImage } from 'lib/utils/captureElementImage'

import { toolbarUploadMedia } from '~/toolbar/toolbarFetch'
import { TOOLBAR_ID } from '~/toolbar/utils'

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

export async function captureElementScreenshot(element: HTMLElement, options?: CaptureOptions): Promise<Blob> {
    return captureElementImage(element, {
        type: 'image/jpeg',
        quality: 0.7,
        filter: screenshotFilter,
        ...options,
    })
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
