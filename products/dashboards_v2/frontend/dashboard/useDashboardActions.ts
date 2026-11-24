import { useMemo } from 'react'

import { showAction } from '../presentation/tileAppearance'
import { downloadImageAction } from './dashboardImage'
import { gridTabs } from './dashboardTypes'
import { useDashboardV2 } from './dashboardV2Context'
import type { MenuAction } from './menuAction'
import { everyTile } from './tileTree'

/**
 * The dashboard's own actions, after the host's `dashboardActions`. `DashboardMenu` shows them; a host with its own menu,
 * such as a scene's menu bar, can render them there instead. Call it inside `DashboardV2View`, such as in its `header`.
 */
export function useDashboardActions(): MenuAction[] {
    const {
        dashboard,
        activeTab,
        widgets,
        disabledReasonFor,
        onEdit,
        downloadImage,
        downloadingImage,
        dashboardActions,
    } = useDashboardV2()
    // The image shows only the tab on screen, so with several tabs the menu names it.
    const label = gridTabs(dashboard).length > 1 ? `Download "${activeTab.title}" tab as image` : 'Download image'
    return useMemo(() => {
        const actions: MenuAction[] = [
            downloadImageAction(label, 'dashboard-v2-download-image', downloadingImage, (format) =>
                downloadImage(format)
            ),
        ]
        const appearance = showAction(
            { key: 'tab-appearance', label: 'All tiles', dataAttr: 'dashboard-v2-tab-appearance' },
            everyTile(activeTab.tiles),
            widgets,
            disabledReasonFor('setTilesSetting'),
            onEdit
        )
        if (appearance) {
            actions.push(appearance)
        }
        return dashboardActions ? dashboardActions(actions) : actions
    }, [label, downloadImage, downloadingImage, dashboardActions, activeTab.tiles, widgets, disabledReasonFor, onEdit])
}
