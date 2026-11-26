import { objectsEqual } from 'lib/utils/objects'

import { type Dashboard, type Tile, isGridTab, isSectionPanel } from '../document/dashboardTypes'

type PlacedTile = { tile: Tile; parentId: string }

function placedTiles(tiles: Tile[], parentId: string, into: Map<string, PlacedTile>): Map<string, PlacedTile> {
    for (const tile of tiles) {
        into.set(tile.id, { tile, parentId })
        if (isSectionPanel(tile.panel)) {
            placedTiles(tile.panel.tiles, tile.id, into)
        }
    }
    return into
}

function tilesOf(dashboard: Dashboard): Map<string, PlacedTile> {
    const tiles = new Map<string, PlacedTile>()
    for (const tab of dashboard.tabs) {
        if (isGridTab(tab)) {
            placedTiles(tab.tiles, tab.id, tiles)
        }
    }
    return tiles
}

function tileName(tile: Tile): string {
    const { panel } = tile
    if (panel.title) {
        return `"${panel.title}"`
    }
    return isSectionPanel(panel) ? 'a section' : `a ${panel.type} tile`
}

// A section's tiles are compared one by one, so its own content leaves them out.
function panelContent(tile: Tile): unknown {
    return isSectionPanel(tile.panel) ? { ...tile.panel, tiles: undefined } : tile.panel
}

/** What changed between two versions of a dashboard, one sentence per change, for a person to read. */
export function describeChanges(before: Dashboard, after: Dashboard): string[] {
    const changes: string[] = []
    if (before.title !== after.title) {
        changes.push(`Renamed the dashboard to "${after.title}"`)
    }
    if (before.description !== after.description) {
        changes.push('Changed the description')
    }

    const tabsBefore = new Map(before.tabs.map((tab) => [tab.id, tab]))
    const tabsAfter = new Map(after.tabs.map((tab) => [tab.id, tab]))
    for (const tab of after.tabs) {
        const old = tabsBefore.get(tab.id)
        if (!old) {
            changes.push(`Added the "${tab.title}" tab`)
        } else if (old.title !== tab.title) {
            changes.push(`Renamed the "${old.title}" tab to "${tab.title}"`)
        }
    }
    for (const tab of before.tabs) {
        if (!tabsAfter.has(tab.id)) {
            changes.push(`Removed the "${tab.title}" tab`)
        }
    }
    const keptBefore = before.tabs.filter((tab) => tabsAfter.has(tab.id)).map((tab) => tab.id)
    const keptAfter = after.tabs.filter((tab) => tabsBefore.has(tab.id)).map((tab) => tab.id)
    if (!objectsEqual(keptBefore, keptAfter)) {
        changes.push('Reordered the tabs')
    }

    const tilesBefore = tilesOf(before)
    const tilesAfter = tilesOf(after)
    for (const [id, { tile, parentId }] of tilesAfter) {
        const old = tilesBefore.get(id)
        if (!old) {
            changes.push(`Added ${tileName(tile)}`)
            continue
        }
        if (old.parentId !== parentId) {
            changes.push(`Moved ${tileName(tile)} to another tab or section`)
        } else if (!objectsEqual(old.tile.place, tile.place)) {
            changes.push(`Moved or resized ${tileName(tile)}`)
        }
        if (!objectsEqual(panelContent(old.tile), panelContent(tile))) {
            changes.push(`Changed ${tileName(tile)}`)
        }
    }
    for (const [id, { tile }] of tilesBefore) {
        if (!tilesAfter.has(id)) {
            changes.push(`Removed ${tileName(tile)}`)
        }
    }

    if (!objectsEqual(before.filters, after.filters) || before.allowFilters !== after.allowFilters) {
        changes.push('Changed the filters')
    }
    if (!objectsEqual(before.time, after.time)) {
        changes.push('Changed the default time range')
    }
    return changes
}
