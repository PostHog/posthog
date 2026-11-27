import posthog from 'posthog-js'

import { downloadImageAction } from '../../dashboard/actions/dashboardImage'
import { type DashboardState, useDashboard } from '../../dashboard/core/dashboardContext'
import { type SectionPanel, gridTabs, panelRef } from '../../dashboard/document/dashboardTypes'
import { everyTile } from '../../dashboard/document/tileTree'
import type { DashboardEdit } from '../../dashboard/edits/dashboardEdits'
import type { MenuAction } from '../../menu/menuAction'
import { type SavedPanel } from '../../panels/core/panelSchema'
import { findPanel } from '../../panels/core/panelSpec'
import { backgroundColorAction, showAction } from './appearanceActions'

/**
 * What a content tile does to itself: its image, parts, background and the panel type's own entries, such as a chart's
 * options. It is the whole menu of a tile shown outside a dashboard.
 */
export function useContentTileActions(id: string, panel: SavedPanel): MenuAction[] {
    const { panels, disabledReasonFor, onEdit, tileActions, downloadImage, downloadingImage } = useDashboard()
    const definition = findPanel(panels, panel.type)
    const actions: MenuAction[] = [tileImageAction(id, downloadingImage, downloadImage)]
    const show = showAction(TILE_SHOW, [{ id, panel }], panels, disabledReasonFor('setTilesAppearance'), onEdit)
    if (show) {
        actions.push(show)
    }
    const backgroundColor = backgroundColorAction(
        TILE_BACKGROUND_COLOR,
        [{ id, panel }],
        panels,
        disabledReasonFor('setTilesAppearance'),
        onEdit
    )
    if (backgroundColor) {
        actions.push(backgroundColor)
    }
    let withPanel = actions
    // It runs while the tile renders, outside any error boundary, so a throw here would break the dashboard.
    try {
        withPanel =
            definition?.menuActions?.(actions, {
                panel,
                setConfig: (config) => onEdit({ edit: 'setPanelConfig', id, config }),
                disabledReason: disabledReasonFor('setPanelConfig'),
            }) ?? actions
    } catch (error) {
        // pinned: error tracking tag, kept from when panels were called widgets.
        posthog.captureException(error, { tag: 'dashboards-v2-widget' })
    }
    // The host runs last, so it has the final say on its page, such as hiding an entry a panel type added.
    return tileActions ? tileActions(withPanel, { id, panel }) : withPanel
}

/** What a person can do to where a content tile sits on the dashboard: its slideshow, its tab, and removing it. */
export function useContentTilePlacementActions(id: string, panel: SavedPanel): MenuAction[] {
    const { dashboard, activeTab, disabledReasonFor, onEdit, tilePlacementActions, showSlideshow } = useDashboard()
    const otherTabs = gridTabs(dashboard).filter((tab) => tab.id !== activeTab.id)
    const actions: MenuAction[] = [
        {
            key: 'slideshow',
            label: 'Slideshow',
            dataAttr: 'dashboard-v2-tile-slideshow-open',
            group: 'view',
            disabledReason: null,
            onSelect: () => showSlideshow(id),
        },
    ]
    if (otherTabs.length > 0) {
        actions.push({
            key: 'move',
            label: 'Move to tab',
            dataAttr: 'dashboard-v2-tile-move-to-tab',
            group: 'dashboard',
            disabledReason: disabledReasonFor('moveTile'),
            submenu: otherTabs.map((tab) => ({
                key: tab.id,
                label: tab.title,
                dataAttr: 'dashboard-v2-tile-move-to-tab-item',
                disabledReason: disabledReasonFor('moveTile'),
                onSelect: () => onEdit({ edit: 'moveTile', id, grid: tab.id }),
            })),
        })
        actions.push({
            key: 'add-to-tab',
            label: 'Also show on tab',
            dataAttr: 'dashboard-v2-tile-add-to-tab',
            group: 'dashboard',
            disabledReason: disabledReasonFor('addToGrid'),
            submenu: otherTabs.map((tab) => {
                // A tab already showing this panel is ticked, and picking it again takes the panel off that tab.
                const shown = panel.ref ? everyTile(tab.tiles).find((tile) => panelRef(tile) === panel.ref) : undefined
                return {
                    key: tab.id,
                    label: tab.title,
                    dataAttr: 'dashboard-v2-tile-add-to-tab-item',
                    checked: !!shown,
                    disabledReason: disabledReasonFor(shown ? 'removeTile' : 'addToGrid'),
                    onSelect: () =>
                        onEdit(shown ? { edit: 'removeTile', id: shown.id } : { edit: 'addToGrid', id, grid: tab.id }),
                }
            }),
        })
    }
    actions.push({
        key: 'remove',
        label: 'Remove tile',
        dataAttr: 'dashboard-v2-tile-remove',
        disabledReason: disabledReasonFor('removeTile'),
        destructive: true,
        onSelect: () => onEdit({ edit: 'removeTile', id }),
    })
    return tilePlacementActions ? tilePlacementActions(actions, { id, panel }) : actions
}

// pinned: `dashboard-v2-tile-parts` data-attrs shipped before border joined this menu.
const TILE_SHOW = { key: 'parts', label: 'Show', dataAttr: 'dashboard-v2-tile-parts' }
const TILE_BACKGROUND_COLOR = {
    key: 'background-color',
    label: 'Background',
    dataAttr: 'dashboard-v2-tile-background-color',
}

function tileImageAction(
    id: string,
    downloadingImage: boolean,
    downloadImage: DashboardState['downloadImage']
): MenuAction {
    return downloadImageAction('Download as image', 'dashboard-v2-tile-download-image', downloadingImage, (format) =>
        downloadImage(format, id)
    )
}

const AUTO_LAYOUT_COLUMNS = [1, 2, 3, 4]

function autoLayoutAction(
    id: string,
    disabledReason: string | null,
    onEdit: (edit: DashboardEdit) => void
): MenuAction {
    return {
        key: 'auto-layout',
        label: 'Auto layout',
        dataAttr: 'dashboard-v2-section-auto-layout',
        disabledReason,
        group: 'display',
        submenu: AUTO_LAYOUT_COLUMNS.map((columns) => ({
            key: String(columns),
            label: columns === 1 ? '1 column' : `${columns} columns`,
            dataAttr: 'dashboard-v2-section-auto-layout-item',
            disabledReason,
            keepOpen: true,
            onSelect: () => onEdit({ edit: 'autoLayout', grid: id, columns }),
        })),
    }
}

export function useSectionActions(id: string, panel: SectionPanel, onStartRename: () => void): MenuAction[] {
    const { panels, disabledReasonFor, onEdit, tileActions, downloadImage, downloadingImage } = useDashboard()
    const show = showAction(TILE_SHOW, [{ id, panel }], panels, disabledReasonFor('setTilesAppearance'), onEdit)
    const actions: MenuAction[] = [
        {
            key: 'rename',
            label: 'Rename',
            dataAttr: 'dashboard-v2-section-menu-rename',
            disabledReason: disabledReasonFor('updateSection'),
            onSelect: onStartRename,
        },
        tileImageAction(id, downloadingImage, downloadImage),
        autoLayoutAction(id, disabledReasonFor('autoLayout'), onEdit),
        ...(show ? [show] : []),
    ]
    return tileActions ? tileActions(actions, { id, panel }) : actions
}

export function useSectionPlacementActions(id: string, panel: SectionPanel): MenuAction[] {
    const { disabledReasonFor, onEdit, tilePlacementActions } = useDashboard()
    const actions: MenuAction[] = [
        {
            key: 'remove',
            label: 'Remove section and its tiles',
            dataAttr: 'dashboard-v2-section-remove',
            disabledReason: disabledReasonFor('removeTile'),
            destructive: true,
            onSelect: () => onEdit({ edit: 'removeTile', id }),
        },
    ]
    return tilePlacementActions ? tilePlacementActions(actions, { id, panel }) : actions
}
