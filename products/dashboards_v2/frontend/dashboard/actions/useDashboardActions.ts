import { useMemo } from 'react'

import type { MenuAction } from '../../menu/menuAction'
import { showAction } from '../../tiles/menu/appearanceActions'
import { contentTilesInOrder } from '../../tiles/TileSlideshow'
import { useDashboard } from '../core/dashboardContext'
import { gridTabs } from '../document/dashboardTypes'
import { everyTile } from '../document/tileTree'
import { imageActions } from './dashboardImage'

/**
 * The dashboard's own actions, after the host's `dashboardActions`. `DashboardMenu` shows them; a host with its own menu,
 * such as a scene's menu bar, can render them there instead. Call it inside `DashboardView`, such as in its `header`.
 */
export function useDashboardActions(): MenuAction[] {
    const {
        dashboard,
        activeTab,
        panels,
        disabledReasonFor,
        onEdit,
        downloadImage,
        copyImage,
        downloadingImage,
        dashboardActions,
        filters,
        showSlideshow,
    } = useDashboard()
    const hasFilterTypes = !!filters && filters.types.length > 0
    const allowFilters = !!dashboard.allowFilters
    // The image shows only the tab on screen, so with several tabs the menu says it is the tab.
    const severalTabs = gridTabs(dashboard).length > 1
    const downloadLabel = severalTabs ? 'Download tab as' : 'Download as'
    const copyLabel = severalTabs ? 'Copy tab as image' : 'Copy as image'
    const firstSlide = contentTilesInOrder(activeTab.tiles)[0]?.id
    return useMemo(() => {
        const actions: MenuAction[] = []
        if (firstSlide) {
            actions.push({
                key: 'slideshow',
                label: 'Slideshow',
                dataAttr: 'dashboard-v2-slideshow-open',
                group: 'view',
                disabledReason: null,
                onSelect: () => showSlideshow(firstSlide),
            })
        }
        actions.push(
            ...imageActions({
                downloadLabel,
                copyLabel,
                dataAttrPrefix: 'dashboard-v2',
                making: downloadingImage,
                download: (format) => downloadImage(format),
                copy: () => copyImage(),
            })
        )
        const appearance = showAction(
            { key: 'tab-appearance', label: 'All tiles', dataAttr: 'dashboard-v2-tab-appearance' },
            everyTile(activeTab.tiles),
            panels,
            disabledReasonFor('setTilesAppearance'),
            onEdit
        )
        if (appearance) {
            actions.push(appearance)
        }
        if (hasFilterTypes) {
            actions.push({
                key: 'allow-filters',
                label: 'Allow filters',
                dataAttr: 'dashboard-v2-allow-filters',
                disabledReason: disabledReasonFor('setAllowFilters'),
                checked: allowFilters,
                onSelect: () => onEdit({ edit: 'setAllowFilters', allowed: !allowFilters }),
            })
        }
        return dashboardActions ? dashboardActions(actions) : actions
    }, [
        firstSlide,
        showSlideshow,
        downloadLabel,
        copyLabel,
        downloadImage,
        copyImage,
        downloadingImage,
        dashboardActions,
        activeTab.tiles,
        panels,
        disabledReasonFor,
        onEdit,
        hasFilterTypes,
        allowFilters,
    ])
}
