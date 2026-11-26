import type { Dashboard, DashboardDocument } from './dashboardTypes'
import { saveDashboard } from './sharedPanels'

/**
 * How a stored board document becomes one this client renders. `products/dashboards/backend/v2/board_schema.py` on the server runs the
 * same steps, so a board reads the same through the API and in the scene.
 *
 * `version` in a document is its schema version. Each entry of `UPGRADES` takes a document at one schema version and
 * returns it at the next, so an old board never needs a data migration. A new panel or query kind that may change
 * shape carries its own `version` the same way, and its own upgrades.
 *
 * Stored documents are not parsed with the strict schemas in `dashboardSchema.ts`: those report a misspelled field in
 * a hand-written dashboard, but here they would drop a field a newer client saved. Objects are spread instead, so an
 * unknown field survives a load, an edit and a save.
 */

export const FIRST_SCHEMA_VERSION = 2
export const CURRENT_SCHEMA_VERSION = 2

type StoredDocument = Record<string, unknown>

// Keyed by the schema version an upgrade starts from. Add an entry and raise `CURRENT_SCHEMA_VERSION` together.
const UPGRADES: Record<number, (document: StoredDocument) => StoredDocument> = {}

export class UnreadableBoardError extends Error {}

type Holder = { tiles?: unknown }

/**
 * Version 2 documents written before panels were named panels call a tile's panel `widget` and the shared ones
 * `widgets`. This renames them and keeps the schema version, because no board was stored under the old names.
 * `renameLegacyPanelFields` in `board_schema.py` does the same on the server.
 */
function renameLegacyPanelFields(stored: StoredDocument): StoredDocument {
    const document: StoredDocument = { ...stored }
    if ('widgets' in document && !('panels' in document)) {
        const { widgets, ...rest } = document
        Object.assign(rest, { panels: widgets })
        return renameLegacyPanelFields(rest)
    }
    if (!Array.isArray(document.tabs)) {
        return document
    }
    const copy = (value: unknown): unknown =>
        typeof value === 'object' && value !== null && !Array.isArray(value) ? { ...value } : value
    document.tabs = document.tabs.map(copy)
    // A loop over a stack, not recursion, so a deeply nested document cannot overflow the call stack.
    const holders = (document.tabs as unknown[]).filter((tab): tab is Holder => typeof tab === 'object' && tab !== null)
    while (holders.length > 0) {
        const holder = holders.pop() as Holder
        if (!Array.isArray(holder.tiles)) {
            continue
        }
        holder.tiles = holder.tiles.map(copy)
        for (const tile of holder.tiles as unknown[]) {
            if (typeof tile !== 'object' || tile === null) {
                continue
            }
            const record = tile as Record<string, unknown>
            if ('widget' in record && !('panel' in record)) {
                record.panel = record.widget
                delete record.widget
            }
            const panel = copy(record.panel)
            if (typeof panel === 'object' && panel !== null && Array.isArray((panel as Holder).tiles)) {
                record.panel = panel
                holders.push(panel as Holder)
            }
        }
    }
    return document
}

/** Returns the stored document at the current schema version, or throws `UnreadableBoardError`. */
export function upgradeBoard(stored: unknown): DashboardDocument {
    if (typeof stored !== 'object' || stored === null || Array.isArray(stored)) {
        throw new UnreadableBoardError('This board is not a dashboard document')
    }
    let document = stored as StoredDocument
    let version = document.version
    if (typeof version !== 'number' || !Number.isInteger(version) || version < FIRST_SCHEMA_VERSION) {
        throw new UnreadableBoardError('This board is not a dashboard document')
    }
    if (version > CURRENT_SCHEMA_VERSION) {
        throw new UnreadableBoardError('This board was saved by a newer version of PostHog. Reload the page.')
    }
    document = renameLegacyPanelFields(document)
    while (version < CURRENT_SCHEMA_VERSION) {
        document = { ...UPGRADES[version](document), version: version + 1 }
        version += 1
    }
    const tabs = document.tabs
    if (!Array.isArray(tabs) || !tabs.some((tab) => typeof tab === 'object' && tab !== null && 'tiles' in tab)) {
        throw new UnreadableBoardError('This board has no tab with tiles')
    }
    // The scene renders these fields as text, so a stored object or array here would throw while rendering.
    const tabIsRenderable = (tab: unknown): boolean =>
        typeof tab === 'object' &&
        tab !== null &&
        typeof (tab as StoredDocument).id === 'string' &&
        typeof (tab as StoredDocument).title === 'string' &&
        (!('tiles' in tab) || Array.isArray((tab as StoredDocument).tiles))
    if (
        typeof document.title !== 'string' ||
        (document.description !== undefined && typeof document.description !== 'string') ||
        !tabs.every(tabIsRenderable)
    ) {
        throw new UnreadableBoardError('This board is not a dashboard document')
    }
    // The viewer's access level comes from access control. A stored one was written by whoever saved the board.
    const { user_access_level: _, ...readable } = document
    return readable as DashboardDocument
}

/** The document to store for a dashboard. The viewer's access level is not part of the board. */
export function boardDocument(dashboard: Dashboard): DashboardDocument {
    const { user_access_level: _, ...document } = saveDashboard(dashboard)
    return document
}
