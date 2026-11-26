import type { Dashboard, DashboardDocument } from './dashboardTypes'
import { saveDashboard } from './sharedWidgets'

/**
 * How a stored board document becomes one this client renders. `products/dashboards/backend/v2/board_schema.py` on the server runs the
 * same steps, so a board reads the same through the API and in the scene.
 *
 * `version` in a document is its schema version. Each entry of `UPGRADES` takes a document at one schema version and
 * returns it at the next, so an old board never needs a data migration. A new widget or query kind that may change
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
    while (version < CURRENT_SCHEMA_VERSION) {
        document = { ...UPGRADES[version](document), version: version + 1 }
        version += 1
    }
    const tabs = document.tabs
    if (!Array.isArray(tabs) || !tabs.some((tab) => typeof tab === 'object' && tab !== null && 'tiles' in tab)) {
        throw new UnreadableBoardError('This board has no tab with tiles')
    }
    return document as DashboardDocument
}

/** The document to store for a dashboard. The viewer's access level is not part of the board. */
export function boardDocument(dashboard: Dashboard): DashboardDocument {
    const { user_access_level: _, ...document } = saveDashboard(dashboard)
    return document
}
