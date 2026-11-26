import type { z } from 'zod'

import type { sharedPanelSchema } from './dashboardSchema'
import { type Dashboard, type DashboardDocument, type Tile, isGridTab, isSectionPanel } from './dashboardTypes'

type DocumentGridTab = Extract<DashboardDocument['tabs'][number], { tiles: unknown }>
type DocumentTile = DocumentGridTab['tiles'][number]
type SharedPanel = z.infer<typeof sharedPanelSchema>

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null && !Array.isArray(value)

/**
 * A stored board can hold a tile the scene cannot draw, because the storage API keeps malformed tiles. Loading leaves
 * such a tile out, so the rest of the board still shows.
 */
function isLoadableTile(tile: unknown): boolean {
    if (!isRecord(tile) || typeof tile.id !== 'string' || !isRecord(tile.place) || !isRecord(tile.panel)) {
        return false
    }
    const panel = tile.panel
    if ('tiles' in panel) {
        return Array.isArray(panel.tiles)
    }
    return 'type' in panel || typeof panel.ref === 'string'
}

function loadTiles(tiles: DocumentTile[], panels: Record<string, SharedPanel>): Tile[] {
    return tiles.flatMap((tile): Tile[] => {
        if (!isLoadableTile(tile)) {
            return []
        }
        const panel = tile.panel
        if ('tiles' in panel) {
            return [{ ...tile, panel: { ...panel, tiles: loadTiles(panel.tiles, panels) } }]
        }
        if ('type' in panel) {
            return [{ ...tile, panel }]
        }
        const shared = Object.hasOwn(panels, panel.ref) ? panels[panel.ref] : undefined
        // `validateDashboard` reports a reference to a missing panel. Loading leaves the tile out.
        return shared ? [{ ...tile, panel: { ...shared, ...panel } }] : []
    })
}

/** Puts each shared panel back on the tiles that show it, so every tile carries its whole panel. */
export function loadDashboard(document: DashboardDocument): Dashboard {
    const { panels = {}, ...dashboard } = document
    return {
        ...dashboard,
        tabs: dashboard.tabs.map((tab) => ('tiles' in tab ? { ...tab, tiles: loadTiles(tab.tiles, panels) } : tab)),
    }
}

function saveTiles(tiles: Tile[], panels: Record<string, SharedPanel>): DocumentTile[] {
    return tiles.map((tile): DocumentTile => {
        const panel = tile.panel
        if (isSectionPanel(panel)) {
            return { ...tile, panel: { ...panel, tiles: saveTiles(panel.tiles, panels) } }
        }
        if (!panel.ref) {
            return tile
        }
        const { ref, parts, appearance, ...content } = panel
        // A ref such as `constructor` or `__proto__` would otherwise reach the object's prototype and never be stored.
        if (!Object.hasOwn(panels, ref)) {
            Object.defineProperty(panels, ref, {
                value: content,
                enumerable: true,
                writable: true,
                configurable: true,
            })
        }
        return { ...tile, panel: { ref, ...(parts && { parts }), ...(appearance && { appearance }) } }
    })
}

/** Stores each shared panel once, in `panels`, and points its tiles at it. A panel no tile shows is dropped. */
export function saveDashboard(dashboard: Dashboard): DashboardDocument {
    const panels: Record<string, SharedPanel> = {}
    const tabs = dashboard.tabs.map((tab) => (isGridTab(tab) ? { ...tab, tiles: saveTiles(tab.tiles, panels) } : tab))
    return Object.keys(panels).length > 0 ? { ...dashboard, panels, tabs } : { ...dashboard, tabs }
}
