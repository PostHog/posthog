import type { z } from 'zod'

import { sharedPanelSchema } from '../../panels/core/panelSchema'
import { type Dashboard, type DashboardDocument, type Tile, isGridTab, isSectionPanel } from './dashboardTypes'

type DocumentGridTab = Extract<DashboardDocument['tabs'][number], { tiles: unknown }>
type DocumentTile = DocumentGridTab['tiles'][number]
type SharedPanel = z.infer<typeof sharedPanelSchema>

const SHARED_KEYS = new Set(Object.keys(sharedPanelSchema.shape))

function loadTiles(tiles: DocumentTile[], panels: Record<string, SharedPanel>): Tile[] {
    return tiles.flatMap((tile): Tile[] => {
        const panel = tile.panel
        if ('tiles' in panel) {
            // `isDashboardDocument` bounds how deep sections nest, so a tile whose `tiles` hang off another kind of
            // panel is left out rather than walked. `validateDashboard` reports it.
            return panel.type === 'section'
                ? [{ ...tile, panel: { ...panel, tiles: loadTiles(panel.tiles, panels) } }]
                : []
        }
        if ('type' in panel) {
            return [{ ...tile, panel }]
        }
        const shared = Object.hasOwn(panels, panel.ref) ? panels[panel.ref] : undefined
        // `validateDashboard` reports a reference to a missing panel, or to a shared section, whose tiles nothing bounds.
        // Loading leaves the tile out.
        return shared && !('tiles' in shared) && shared.type !== 'section'
            ? [{ ...tile, panel: { ...shared, ...panel } }]
            : []
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
        const { ref } = panel
        // Fields a host added stay on the tile, so two tiles of one panel keep their own values.
        const content: Record<string, unknown> = {}
        const own: Record<string, unknown> = Object.create(null)
        for (const [key, value] of Object.entries(panel)) {
            if (value !== undefined) {
                ;(SHARED_KEYS.has(key) ? content : own)[key] = value
            }
        }
        // A ref such as `constructor` or `__proto__` would otherwise reach the object's prototype and never be stored.
        if (!Object.hasOwn(panels, ref)) {
            Object.defineProperty(panels, ref, {
                value: content,
                enumerable: true,
                writable: true,
                configurable: true,
            })
        }
        return { ...tile, panel: own as DocumentTile['panel'] }
    })
}

/** Stores each shared panel once, in `panels`, and points its tiles at it. A panel no tile shows is dropped. */
export function saveDashboard(dashboard: Dashboard): DashboardDocument {
    const panels: Record<string, SharedPanel> = {}
    const tabs = dashboard.tabs.map((tab) => (isGridTab(tab) ? { ...tab, tiles: saveTiles(tab.tiles, panels) } : tab))
    return Object.keys(panels).length > 0 ? { ...dashboard, panels, tabs } : { ...dashboard, tabs }
}
