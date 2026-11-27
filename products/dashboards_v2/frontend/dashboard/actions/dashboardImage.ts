import { canCopyImageToClipboard, captureElementAsImage } from 'lib/utils/copyImageToClipboard'
import { downloadFile } from 'lib/utils/dom'
import { slugify } from 'lib/utils/strings'

import type { MenuAction } from '../../menu/menuAction'
import { INTERACTIVE_ONLY_CLASS } from '../../tiles/core/ContentTile'

export type ImageFormat = 'png' | 'webp'

export const IMAGE_FORMATS: { format: ImageFormat; label: string }[] = [
    { format: 'png', label: 'PNG' },
    { format: 'webp', label: 'WebP' },
]

const LEFT_OUT = `.TileActions, .${INTERACTIVE_ONLY_CLASS}, .react-resizable-handle, .TileGrid__drop-preview, .DashboardActions, [data-attr="dashboard-v2-add-tab"]`
const NOT_READY = '.DashboardTileGrid__placeholder, [aria-busy="true"]'
const READY_TIMEOUT_MS = 20000
const POLL_MS = 100

/** Safari's canvas cannot write WebP and quietly writes a PNG instead, so the menu offers only what the browser writes. */
export function canWriteImage(format: ImageFormat): boolean {
    return document.createElement('canvas').toDataURL(`image/${format}`).startsWith(`data:image/${format}`)
}

/** A busy element the capture leaves out never shows in the image, so it does not hold the capture back. */
function isLoading(root: HTMLElement): boolean {
    return Array.from(root.querySelectorAll(NOT_READY)).some((element) => {
        const leftOut = element.closest(LEFT_OUT)
        return !leftOut || !root.contains(leftOut)
    })
}

async function waitUntilReady(root: HTMLElement): Promise<void> {
    const deadline = Date.now() + READY_TIMEOUT_MS
    do {
        await new Promise((resolve) => setTimeout(resolve, POLL_MS))
    } while (isLoading(root) && Date.now() < deadline)
    if (isLoading(root)) {
        throw new Error('The dashboard did not finish loading in time to capture it.')
    }
}

export async function downloadDashboardImage(root: HTMLElement, title: string, format: ImageFormat): Promise<void> {
    await waitUntilReady(root)
    const blob = await captureElementAsImage(root, LEFT_OUT, `image/${format}`)
    downloadFile(new File([blob], `${slugify(title) || 'dashboard'}.${format}`, { type: blob.type }))
}

/**
 * Call it straight from the click, before any await. Safari refuses a clipboard write that starts later, so the
 * clipboard gets the pending image. Browsers take only PNG on the clipboard.
 */
export async function copyDashboardImage(root: HTMLElement): Promise<void> {
    const image = waitUntilReady(root).then(() => captureElementAsImage(root, LEFT_OUT))
    // The write never reads the promise when it throws first, and an unread rejection would be reported as unhandled.
    image.catch(() => {})
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': image })])
}

/** `download-image` with a format submenu, then `copy-image` on a browser that can put an image on the clipboard. */
export function imageActions({
    downloadLabel,
    copyLabel,
    dataAttrPrefix,
    busy: makingImage,
    download,
    copy,
}: {
    downloadLabel: string
    copyLabel: string
    dataAttrPrefix: string
    busy: boolean
    download: (format: ImageFormat) => void
    copy: () => void
}): MenuAction[] {
    const busy = makingImage ? 'Making the image' : null
    const dataAttr = `${dataAttrPrefix}-download-image`
    const actions: MenuAction[] = [
        {
            key: 'download-image',
            label: downloadLabel,
            dataAttr,
            group: 'view',
            needsLoaded: true,
            disabledReason: busy,
            loading: makingImage,
            submenu: IMAGE_FORMATS.filter(({ format }) => canWriteImage(format)).map(({ format, label }) => ({
                key: format,
                label,
                dataAttr: `${dataAttr}-${format}`,
                disabledReason: busy,
                onSelect: () => download(format),
            })),
        },
    ]
    if (canCopyImageToClipboard()) {
        actions.push({
            key: 'copy-image',
            label: copyLabel,
            dataAttr: `${dataAttrPrefix}-copy-image`,
            group: 'view',
            needsLoaded: true,
            disabledReason: busy,
            loading: makingImage,
            onSelect: copy,
        })
    }
    return actions
}
