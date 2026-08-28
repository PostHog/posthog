import { toBlob } from 'html-to-image'

import { toolbarUploadMedia } from '~/toolbar/toolbarFetch'
import { TOOLBAR_ID } from '~/toolbar/utils'

export interface ElementScreenshot {
    mediaId: string
}

function screenshotFilter(node: Node): boolean {
    return !(node instanceof HTMLElement && node.id === TOOLBAR_ID)
}

let cachedStylePropertyNames: string[] | null = null

const getAllStylePropertyNames = (): string[] => {
    if (cachedStylePropertyNames) {
        return cachedStylePropertyNames
    }
    const names: string[] = []
    const style = getComputedStyle(document.documentElement)
    for (let i = 0; i < style.length; i++) {
        const name = style[i]
        if (!name.startsWith('--')) {
            names.push(name)
        }
    }
    cachedStylePropertyNames = names
    return names
}

export interface CaptureOptions {
    pixelRatio?: number
    width?: number
    height?: number
    backgroundColor?: string
}

export async function captureElementScreenshot(element: HTMLElement, options?: CaptureOptions): Promise<Blob> {
    const blob = await toBlob(element, {
        type: 'image/jpeg',
        includeStyleProperties: getAllStylePropertyNames(),
        quality: 0.7,
        filter: screenshotFilter,
        ...options,
    })

    if (!blob) {
        throw new Error('Failed to capture element screenshot')
    }

    return blob
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
