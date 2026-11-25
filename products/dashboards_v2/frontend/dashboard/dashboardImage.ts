import { captureElementAsImage } from 'lib/utils/copyImageToClipboard'
import { downloadFile } from 'lib/utils/dom'
import { slugify } from 'lib/utils/strings'

export type ImageFormat = 'png' | 'webp'

export const IMAGE_FORMATS: { format: ImageFormat; label: string }[] = [
    { format: 'png', label: 'PNG' },
    { format: 'webp', label: 'WebP' },
]

const LEFT_OUT =
    '.TileHoverReveal, .react-resizable-handle, .TileGrid__drop-preview, .DashboardV2Actions, [data-attr="dashboard-v2-add-tab"]'
const NOT_READY = '.DashboardTileGrid__placeholder, [aria-busy="true"]'
const READY_TIMEOUT_MS = 20000
const POLL_MS = 100

/** Safari's canvas cannot write WebP and quietly writes a PNG instead, so the menu offers only what the browser writes. */
export function canWriteImage(format: ImageFormat): boolean {
    return document.createElement('canvas').toDataURL(`image/${format}`).startsWith(`data:image/${format}`)
}

async function waitUntilReady(root: HTMLElement): Promise<void> {
    const deadline = Date.now() + READY_TIMEOUT_MS
    do {
        await new Promise((resolve) => setTimeout(resolve, POLL_MS))
    } while (root.querySelector(NOT_READY) && Date.now() < deadline)
}

export async function downloadDashboardImage(root: HTMLElement, title: string, format: ImageFormat): Promise<void> {
    await waitUntilReady(root)
    const blob = await captureElementAsImage(root, LEFT_OUT, `image/${format}`)
    downloadFile(new File([blob], `${slugify(title) || 'dashboard'}.${format}`, { type: blob.type }))
}
