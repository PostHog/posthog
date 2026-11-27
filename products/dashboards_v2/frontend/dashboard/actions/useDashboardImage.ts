import { type RefObject, useCallback, useState } from 'react'

// lemonToast shows quill's toasts wherever the app mounts them, so it is the one toast API here too.
// oxlint-disable-next-line no-restricted-imports
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { type Dashboard, activeGridTab, gridTabs } from '../document/dashboardTypes'
import { findTile } from '../document/tileTree'
import { type ImageFormat, copyDashboardImage, downloadDashboardImage } from './dashboardImage'

function imageWords(
    dashboard: Dashboard,
    activeTabId: string | null,
    tileId: string | undefined,
    done: 'downloaded' | 'copied'
): { file: string; pending: string; success: string } {
    const tile = tileId ? findTile(dashboard, tileId) : null
    if (tile?.panel.title) {
        const title = tile.panel.title
        return {
            file: `${dashboard.title} ${title}`,
            pending: `Drawing "${title}"`,
            success: `Image of "${title}" ${done}`,
        }
    }
    if (tile) {
        return {
            file: `${dashboard.title} tile`,
            pending: 'Drawing the tile',
            success: `Image of the tile ${done}`,
        }
    }
    const tab = activeGridTab(dashboard, activeTabId).title
    if (gridTabs(dashboard).length > 1) {
        return {
            file: `${dashboard.title} ${tab}`,
            pending: `Drawing every tile on the "${tab}" tab`,
            success: `Image of the "${tab}" tab ${done}`,
        }
    }
    return { file: dashboard.title, pending: 'Drawing every tile', success: `Image ${done}` }
}

/**
 * Downloads or copies the tab under `rootRef`, or with `tileId` one tile, as an image. While it runs, `capturing` says what to
 * mount, so the image has no placeholders: the whole tab, or that tile only.
 */
export function useDashboardImage(
    rootRef: RefObject<HTMLElement | null>,
    dashboard: Dashboard,
    activeTabId: string | null
): {
    capturing: { tileId?: string } | null
    downloadImage: (format: ImageFormat, tileId?: string) => Promise<void>
    copyImage: (tileId?: string) => Promise<void>
} {
    const [capturing, setCapturing] = useState<{ tileId?: string } | null>(null)
    const exportImage = useCallback(
        async (tileId: string | undefined, format: ImageFormat | 'clipboard'): Promise<void> => {
            const page = rootRef.current
            const root = tileId ? page?.querySelector<HTMLElement>(`[data-dv2-tile="${CSS.escape(tileId)}"]`) : page
            if (!root) {
                return
            }
            setCapturing({ tileId })
            try {
                const toClipboard = format === 'clipboard'
                const words = imageWords(dashboard, activeTabId, tileId, toClipboard ? 'copied' : 'downloaded')
                const image = toClipboard ? copyDashboardImage(root) : downloadDashboardImage(root, words.file, format)
                await lemonToast.promise(image, {
                    pending: words.pending,
                    success: words.success,
                    error: toClipboard
                        ? 'Could not copy the image. Try again, or download it.'
                        : 'Could not create the image. Try again.',
                })
            } catch {
                // The toast already says it failed.
            } finally {
                setCapturing(null)
            }
        },
        [rootRef, dashboard, activeTabId]
    )
    const downloadImage = useCallback(
        (format: ImageFormat, tileId?: string) => exportImage(tileId, format),
        [exportImage]
    )
    const copyImage = useCallback((tileId?: string) => exportImage(tileId, 'clipboard'), [exportImage])
    return { capturing, downloadImage, copyImage }
}
