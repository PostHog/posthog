import { useMemo } from 'react'

import { IMAGE_FORMATS, canWriteImage } from './dashboardImage'
import { gridTabs } from './dashboardTypes'
import { useDashboardV2 } from './dashboardV2Context'
import type { MenuAction } from './menuAction'

/**
 * The dashboard's own actions, after the host's `dashboardActions`. `DashboardMenu` shows them; a host with its own menu,
 * such as a scene's menu bar, can render them there instead. Call it inside `DashboardV2View`, such as in its `header`.
 */
export function useDashboardActions(): MenuAction[] {
    const { dashboard, activeTab, downloadImage, downloadingImage, dashboardActions } = useDashboardV2()
    // The image shows only the tab on screen, so with several tabs the menu names it.
    const label = gridTabs(dashboard).length > 1 ? `Download "${activeTab.title}" tab as image` : 'Download image'
    return useMemo(() => {
        const busy = downloadingImage ? 'Making the image' : null
        const actions: MenuAction[] = [
            {
                key: 'download-image',
                label,
                dataAttr: 'dashboard-v2-download-image',
                disabledReason: busy,
                submenu: IMAGE_FORMATS.filter(({ format }) => canWriteImage(format)).map(({ format, label }) => ({
                    key: format,
                    label,
                    dataAttr: `dashboard-v2-download-image-${format}`,
                    disabledReason: busy,
                    onSelect: () => downloadImage(format),
                })),
            },
        ]
        return dashboardActions ? dashboardActions(actions) : actions
    }, [label, downloadImage, downloadingImage, dashboardActions])
}
