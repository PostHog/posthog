import { captureElementImage } from 'lib/utils/captureElementImage'

/**
 * `copied` — a PNG of the element is on the clipboard.
 * `unsupported` — the browser exposes no way to put an image on the clipboard.
 * `failed` — the capture or the clipboard write was attempted and did not land.
 */
export type CopyImageOutcome = 'copied' | 'unsupported' | 'failed'

/** The blob comes back so the caller can reuse the capture instead of rendering the element twice. */
export type CopyImageResult = { outcome: 'copied'; blob: Blob } | { outcome: 'unsupported' | 'failed'; blob: null }

const CLIPBOARD_IMAGE_TYPE = 'image/png'

export function canCopyImageToClipboard(): boolean {
    return typeof ClipboardItem !== 'undefined' && !!navigator.clipboard?.write
}

export async function captureElementAsPng(element: HTMLElement): Promise<Blob> {
    return captureElementImage(element, {
        type: CLIPBOARD_IMAGE_TYPE,
        // Charts are read at a glance after being pasted, so capture at 2x to keep text and lines sharp.
        pixelRatio: 2,
        // Anything the element leaves transparent shows the page behind it, which turns into a
        // checkerboard or a black box once pasted. Fill it with the page background instead.
        backgroundColor: getComputedStyle(document.body).backgroundColor || undefined,
    })
}

export async function copyElementImageToClipboard(element: HTMLElement): Promise<CopyImageResult> {
    if (!canCopyImageToClipboard()) {
        return { outcome: 'unsupported', blob: null }
    }

    // Safari only accepts a clipboard write that starts in the same task as the click, so the pending
    // capture goes onto the ClipboardItem rather than being awaited first. Attach a no-op handler as
    // well, because the write never observes the promise if the ClipboardItem constructor throws.
    const capture = captureElementAsPng(element)
    capture.catch(() => {})

    try {
        await navigator.clipboard.write([new ClipboardItem({ [CLIPBOARD_IMAGE_TYPE]: capture })])
        return { outcome: 'copied', blob: await capture }
    } catch {
        return { outcome: 'failed', blob: null }
    }
}
