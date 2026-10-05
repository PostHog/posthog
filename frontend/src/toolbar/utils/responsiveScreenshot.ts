import { delay } from 'lib/utils/async'

import { TOOLBAR_ID } from '~/toolbar/utils'
import { captureElementScreenshot } from '~/toolbar/utils/screenshot'

export const RESPONSIVE_CAPTURE_WIDTHS = [320, 375, 425, 768, 1024, 1440, 1920]

const PER_WIDTH_SETTLE_TIMEOUT_MS = 4000

export interface WidthCapture {
    width: number
    blob: Blob
}

function buildReflowIframe(width: number): HTMLIFrameElement {
    const iframe = document.createElement('iframe')
    iframe.setAttribute('sandbox', 'allow-same-origin')
    iframe.setAttribute('aria-hidden', 'true')
    iframe.setAttribute('tabindex', '-1')
    iframe.style.cssText = `position:fixed;top:0;left:-100000px;width:${width}px;height:${window.innerHeight}px;border:0;`
    document.body.appendChild(iframe)
    return iframe
}

function populateIframe(iframe: HTMLIFrameElement): void {
    const doc = iframe.contentDocument
    if (!doc) {
        throw new Error('Reflow iframe has no document')
    }

    const importedHtml = doc.importNode(document.documentElement, true)

    importedHtml.querySelectorAll('script, noscript').forEach((node) => node.remove())
    importedHtml.querySelector(`#${TOOLBAR_ID}`)?.remove()

    let head = importedHtml.querySelector('head')
    if (!head) {
        head = doc.createElement('head')
        importedHtml.insertBefore(head, importedHtml.firstChild)
    }
    const base = doc.createElement('base')
    base.href = document.baseURI
    head.insertBefore(base, head.firstChild)

    doc.replaceChild(importedHtml, doc.documentElement)

    copyCanvases(doc)
}

function copyCanvases(doc: Document): void {
    const liveCanvases = document.querySelectorAll('canvas')
    const clonedCanvases = doc.querySelectorAll('canvas')
    clonedCanvases.forEach((cloned, index) => {
        const live = liveCanvases[index] as HTMLCanvasElement | undefined
        if (!live || live.width === 0 || live.height === 0) {
            return
        }
        try {
            const clonedCanvas = cloned as HTMLCanvasElement
            clonedCanvas.width = live.width
            clonedCanvas.height = live.height
            clonedCanvas.getContext('2d')?.drawImage(live, 0, 0)
        } catch {}
    })
}

function waitForResource(el: HTMLLinkElement | HTMLImageElement, isReady: boolean): Promise<void> {
    if (isReady) {
        return Promise.resolve()
    }
    return new Promise<void>((resolve) => {
        el.addEventListener('load', () => resolve(), { once: true })
        el.addEventListener('error', () => resolve(), { once: true })
    })
}

async function waitForSettle(iframe: HTMLIFrameElement): Promise<void> {
    const doc = iframe.contentDocument
    if (!doc) {
        return
    }

    const settled = (async (): Promise<void> => {
        const links = Array.from(doc.querySelectorAll<HTMLLinkElement>('link[rel~="stylesheet"]'))
        await Promise.all(links.map((link) => waitForResource(link, !!link.sheet)))
        await delay(0)
        try {
            await doc.fonts?.ready
        } catch {}
        iframe.style.height = `${doc.documentElement.scrollHeight}px`
        await delay(150)
        await Promise.all(Array.from(doc.images).map((img) => waitForResource(img, img.complete)))
    })()

    await Promise.race([settled, delay(PER_WIDTH_SETTLE_TIMEOUT_MS)])
}

async function captureWidth(width: number): Promise<Blob> {
    const iframe = buildReflowIframe(width)
    try {
        populateIframe(iframe)
        await waitForSettle(iframe)
        const doc = iframe.contentDocument
        if (!doc) {
            throw new Error('Reflow iframe document went away')
        }
        return await captureElementScreenshot(doc.documentElement, {
            pixelRatio: 1,
            width,
            height: doc.documentElement.scrollHeight,
            backgroundColor: '#ffffff',
        })
    } finally {
        iframe.remove()
    }
}

export async function captureResponsiveScreenshots(
    widths: number[] = RESPONSIVE_CAPTURE_WIDTHS,
    onProgress?: (done: number, total: number) => void
): Promise<WidthCapture[]> {
    const captures: WidthCapture[] = []
    let attempted = 0
    for (const width of widths) {
        try {
            const blob = await captureWidth(width)
            captures.push({ width, blob })
        } catch {}
        attempted++
        onProgress?.(attempted, widths.length)
    }
    return captures
}
