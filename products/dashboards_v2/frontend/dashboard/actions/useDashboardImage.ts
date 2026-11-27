import { type RefObject, useCallback, useState } from 'react'

// TODO(2026-11-25): Replace with quill once it can; the app does not mount quill's ToastProvider yet.
// oxlint-disable-next-line no-restricted-imports
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { type Dashboard, activeGridTab, gridTabs } from '../document/dashboardTypes'
import { findTile } from '../document/tileTree'
import { type ImageFormat, downloadDashboardImage } from './dashboardImage'

function imageWords(
    dashboard: Dashboard,
    activeTabId: string | null,
    tileId: string | undefined
): { file: string; pending: string; success: string } {
    const tile = tileId ? findTile(dashboard, tileId) : null
    if (tile?.panel.title) {
        const title = tile.panel.title
        return {
            file: `${dashboard.title} ${title}`,
            pending: `Drawing "${title}"`,
            success: `Image of "${title}" downloaded`,
        }
    }
    if (tile) {
        return {
            file: `${dashboard.title} tile`,
            pending: 'Drawing the tile',
            success: 'Image of the tile downloaded',
        }
    }
    const tab = activeGridTab(dashboard, activeTabId).title
    if (gridTabs(dashboard).length > 1) {
        return {
            file: `${dashboard.title} ${tab}`,
            pending: `Drawing every tile on the "${tab}" tab`,
            success: `Image of the "${tab}" tab downloaded`,
        }
    }
    return { file: dashboard.title, pending: 'Drawing every tile', success: 'Image downloaded' }
}

/**
 * Downloads the tab under `rootRef`, or with `tileId` one tile, as an image. While it runs, `capturing` says what to
 * mount, so the image has no placeholders: the whole tab, or that tile only.
 */
export function useDashboardImage(
    rootRef: RefObject<HTMLElement | null>,
    dashboard: Dashboard,
    activeTabId: string | null
): {
    capturing: { tileId?: string } | null
    downloadImage: (format: ImageFormat, tileId?: string) => Promise<void>
} {
    const [capturing, setCapturing] = useState<{ tileId?: string } | null>(null)
    const downloadImage = useCallback(
        async (format: ImageFormat, tileId?: string): Promise<void> => {
            const page = rootRef.current
            const root = tileId ? page?.querySelector<HTMLElement>(`[data-dv2-tile="${CSS.escape(tileId)}"]`) : page
            if (!root) {
                return
            }
            setCapturing({ tileId })
            try {
                const words = imageWords(dashboard, activeTabId, tileId)
                await lemonToast.promise(downloadDashboardImage(root, words.file, format), {
                    pending: words.pending,
                    success: words.success,
                    error: 'Could not create the image. Try again.',
                })
            } catch {
                // The toast already says it failed.
            } finally {
                setCapturing(null)
            }
        },
        [rootRef, dashboard, activeTabId]
    )
    return { capturing, downloadImage }
}
