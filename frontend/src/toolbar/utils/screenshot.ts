import { toBlob } from 'html-to-image'

import { toolbarUploadMedia } from '~/toolbar/toolbarFetch'
import { TOOLBAR_ID, toError } from '~/toolbar/utils'

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

function describeElement(element: HTMLElement): string {
    return `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ''}`
}

export async function captureElementScreenshot(element: HTMLElement, options?: CaptureOptions): Promise<Blob> {
    let blob: Blob | null
    try {
        blob = await toBlob(element, {
            type: 'image/jpeg',
            includeStyleProperties: getAllStylePropertyNames(),
            quality: 0.7,
            filter: screenshotFilter,
            ...options,
        })
    } catch (error) {
        // html-to-image rejects with a raw DOM Event when a resource on the page fails to load.
        // Rethrow a real Error so the failure reaches error tracking with a message and a stack.
        throw toError(error, `Failed to capture screenshot of ${describeElement(element)}`)
    }

    if (!blob) {
        throw new Error(`Failed to capture screenshot of ${describeElement(element)}`)
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
