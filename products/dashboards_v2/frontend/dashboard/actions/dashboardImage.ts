import {
    canCopyImageToClipboard,
    captureElementAsImage,
    writePendingImageToClipboard,
} from 'lib/utils/copyImageToClipboard'
import { downloadFile } from 'lib/utils/dom'
import { slugify } from 'lib/utils/strings'

import type { MenuAction } from '../../menu/menuAction'
import { INTERACTIVE_ONLY_CLASS } from '../../tiles/core/ContentTile'
import { TILE_PLACEHOLDER_CLASS } from '../../tiles/core/TileContextMenu'

export type ImageFormat = 'png' | 'webp'

export const IMAGE_FORMATS: { format: ImageFormat; label: string }[] = [
    { format: 'png', label: 'PNG' },
    { format: 'webp', label: 'WebP' },
]

const LEFT_OUT = `.TileActions, .${INTERACTIVE_ONLY_CLASS}, .react-resizable-handle, .TileGrid__drop-preview, .DashboardActions, [data-attr="dashboard-v2-add-tab"]`
const NOT_READY = `.${TILE_PLACEHOLDER_CLASS}, [aria-busy="true"]`
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

async function waitUntilReady(root: HTMLElement, signal?: AbortSignal): Promise<void> {
    const deadline = Date.now() + READY_TIMEOUT_MS
    do {
        await new Promise((resolve) => setTimeout(resolve, POLL_MS))
        signal?.throwIfAborted()
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

/** Call it straight from the click, before any await: see `writePendingImageToClipboard`. The clipboard takes only PNG. */
export async function copyDashboardImage(root: HTMLElement): Promise<void> {
    const abort = new AbortController()
    const image = waitUntilReady(root, abort.signal).then(() => captureElementAsImage(root, LEFT_OUT))
    try {
        await writePendingImageToClipboard(image)
    } catch (error) {
        // A refused write never reads the image, so stop waiting rather than draw it for nothing.
        abort.abort()
        throw error
    }
}

/** `download-image` with a format submenu, then `copy-image` on a browser that can put an image on the clipboard. */
export function imageActions({
    downloadLabel,
    copyLabel,
    dataAttrPrefix,
    making,
    download,
    copy,
}: {
    downloadLabel: string
    copyLabel: string
    dataAttrPrefix: string
    /** An image is being made, so both entries wait. */
    making: boolean
    download: (format: ImageFormat) => void
    copy: () => void
}): MenuAction[] {
    const waiting = making ? { disabledReason: 'Making the image', loading: true as const } : { disabledReason: null }
    const dataAttr = `${dataAttrPrefix}-download-image`
    const actions: MenuAction[] = [
        {
            key: 'download-image',
            label: downloadLabel,
            dataAttr,
            group: 'view',
            needsLoaded: true,
            ...waiting,
            submenu: IMAGE_FORMATS.filter(({ format }) => canWriteImage(format)).map(({ format, label }) => ({
                key: format,
                label,
                dataAttr: `${dataAttr}-${format}`,
                disabledReason: waiting.disabledReason,
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
            ...waiting,
            onSelect: copy,
        })
    }
    return actions
}
