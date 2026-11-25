import type { z } from 'zod'

import type { sharedWidgetSchema } from './dashboardSchema'
import { type Dashboard, type DashboardDocument, type Tile, isGridTab, isSectionWidget } from './dashboardTypes'

type DocumentGridTab = Extract<DashboardDocument['tabs'][number], { tiles: unknown }>
type DocumentTile = DocumentGridTab['tiles'][number]
type SharedWidget = z.infer<typeof sharedWidgetSchema>

function loadTiles(tiles: DocumentTile[], widgets: Record<string, SharedWidget>): Tile[] {
    return tiles.flatMap((tile): Tile[] => {
        const widget = tile.widget
        if ('tiles' in widget) {
            return [{ ...tile, widget: { ...widget, tiles: loadTiles(widget.tiles, widgets) } }]
        }
        if ('type' in widget) {
            return [{ ...tile, widget }]
        }
        const shared = Object.hasOwn(widgets, widget.ref) ? widgets[widget.ref] : undefined
        // `validateDashboard` reports a reference to a missing widget. Loading leaves the tile out.
        return shared ? [{ ...tile, widget: { ...shared, ...widget } }] : []
    })
}

/** Puts each shared widget back on the tiles that show it, so every tile carries its whole widget. */
export function loadDashboard(document: DashboardDocument): Dashboard {
    const { widgets = {}, ...dashboard } = document
    return {
        ...dashboard,
        tabs: dashboard.tabs.map((tab) => ('tiles' in tab ? { ...tab, tiles: loadTiles(tab.tiles, widgets) } : tab)),
    }
}

function saveTiles(tiles: Tile[], widgets: Record<string, SharedWidget>): DocumentTile[] {
    return tiles.map((tile): DocumentTile => {
        const widget = tile.widget
        if (isSectionWidget(widget)) {
            return { ...tile, widget: { ...widget, tiles: saveTiles(widget.tiles, widgets) } }
        }
        if (!widget.ref) {
            return tile
        }
        const { ref, parts, appearance, ...content } = widget
        // A ref such as `constructor` or `__proto__` would otherwise reach the object's prototype and never be stored.
        if (!Object.hasOwn(widgets, ref)) {
            Object.defineProperty(widgets, ref, {
                value: content,
                enumerable: true,
                writable: true,
                configurable: true,
            })
        }
        return { ...tile, widget: { ref, ...(parts && { parts }), ...(appearance && { appearance }) } }
    })
}

/** Stores each shared widget once, in `widgets`, and points its tiles at it. A widget no tile shows is dropped. */
export function saveDashboard(dashboard: Dashboard): DashboardDocument {
    const widgets: Record<string, SharedWidget> = {}
    const tabs = dashboard.tabs.map((tab) => (isGridTab(tab) ? { ...tab, tiles: saveTiles(tab.tiles, widgets) } : tab))
    return Object.keys(widgets).length > 0 ? { ...dashboard, widgets, tabs } : { ...dashboard, tabs }
}
