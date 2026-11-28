import { z } from 'zod'

import { type FilterSpec, findFilterType, hasFilterOn } from '../../filters/filterSpec'
import { sharedPanelSchema, type SavedPanel } from '../../panels/core/panelSchema'
import { type PanelTypeSpec, findPanel, sizeOfPanels } from '../../panels/core/panelSpec'
import {
    dashboardDocumentSchema,
    documentContentPanelSchema,
    gridTabSchema,
    linkTabSchema,
    ONE_GRID_TAB,
    sectionPanelSchema,
    tileSchema,
    panelRefSchema,
} from './dashboardSchema'
import { type DashboardDocument, type SavedFilter, GRID } from './dashboardTypes'

// Deeper than anyone builds by hand, and shallow enough that walking a hostile document cannot overflow the stack.
export const MAX_SECTION_DEPTH = 10

export type DashboardProblem = {
    /** Where the problem is, such as `tabs[0].tiles[2].panel.config.query`. */
    path: string
    message: string
}

// Loading spreads a shared panel onto each of its tiles, so a `parts` saved here would show on every tile.
const SHARED_PANEL_TILE_FIELD = 'A shared panel holds content only. Each tile sets its own parts and appearance'
const ON_SHARED_PANEL: Record<string, string> = {
    parts: SHARED_PANEL_TILE_FIELD,
    appearance: SHARED_PANEL_TILE_FIELD,
    ref: 'A shared panel has no ref of its own',
    tiles: 'Only a section holds tiles',
}
const ON_CONTENT_PANEL: Record<string, string> = {
    ref: 'Only a tile that shows a shared panel has a ref, and it holds no other content',
    tiles: 'Only a section holds tiles',
}
// Loading spreads a reference over its shared panel, so content here would replace the checked content.
const REF_CONTENT = 'A tile that shows a shared panel takes its content from the panel'
const ON_PANEL_REF: Record<string, string> = Object.fromEntries([
    ...['type', 'title', 'description', 'refreshedAt', 'config'].map((key) => [key, REF_CONTENT]),
    ['tiles', 'Only a section holds tiles'],
])

// The document schemas, with each panel checked only for a `type` at first. A panel's fields depend on its type, so
// the walk below checks each one against the schema for that type, which gives a clearer problem than a failed union.
const panelHeadSchema = z.looseObject({ type: z.string() })
type PanelHead = z.infer<typeof panelHeadSchema>
const tileHeadSchema = tileSchema.extend({ panel: z.union([panelHeadSchema, panelRefSchema.loose()]) })
type TileHead = z.infer<typeof tileHeadSchema>
const sectionHeadSchema = sectionPanelSchema.extend({ tiles: z.array(tileHeadSchema) })
const dashboardHeadSchema = dashboardDocumentSchema.extend({
    panels: z.record(z.string(), panelHeadSchema).optional(),
    tabs: z
        .array(z.union([gridTabSchema.extend({ tiles: z.array(tileHeadSchema) }), linkTabSchema]))
        .refine((tabs) => tabs.some((tab) => 'tiles' in tab), ONE_GRID_TAB),
})

// Loading walks the tiles of any panel that has them, so only a section may, and it must.
function sectionsHaveTiles(tiles: TileHead[], depth: number): boolean {
    return tiles.every((tile) => {
        if (!('type' in tile.panel) || tile.panel.type !== 'section') {
            return !('tiles' in tile.panel)
        }
        const section = sectionHeadSchema.safeParse(tile.panel)
        return depth < MAX_SECTION_DEPTH && section.success && sectionsHaveTiles(section.data.tiles, depth + 1)
    })
}

/** Whether a document has the shape of a dashboard. It checks each panel only for a `type`, as each panel type checks the rest. */
export function isDashboardDocument(document: unknown): document is DashboardDocument {
    const parsed = dashboardHeadSchema.safeParse(document)
    return parsed.success && parsed.data.tabs.every((tab) => !('tiles' in tab) || sectionsHaveTiles(tab.tiles, 0))
}

function issuesAt(path: string, error: z.ZodError): DashboardProblem[] {
    return error.issues.map((issue) => ({
        path: [path, ...issue.path.map((key) => (typeof key === 'number' ? `[${key}]` : `.${String(key)}`))]
            .join('')
            .replace(/^\./, ''),
        message: issue.message,
    }))
}

/**
 * Checks a dashboard document before anything loads it, such as a JSON file in a repo, a document an MCP tool wrote,
 * or a saved dashboard from the API. `panels` are the types the host can show, and `filters` the kinds of filter it
 * supports. An empty result means it is valid.
 * Overlaps and gaps are not problems, because loading the dashboard settles them.
 */
export function validateDashboard(
    document: unknown,
    panels: PanelTypeSpec[],
    filters: FilterSpec[] = []
): DashboardProblem[] {
    const parsed = dashboardHeadSchema.safeParse(document)
    if (!parsed.success) {
        return issuesAt('', parsed.error)
    }
    const problems: DashboardProblem[] = []
    const sizeOf = sizeOfPanels(panels)
    const seenIds = new Set<string>()

    // Parsing drops fields it doesn't know, so a field that belongs elsewhere in the document is checked by hand.
    const checkContent = (
        panel: PanelHead,
        path: string,
        schema: z.ZodType<SavedPanel>,
        misplaced: Record<string, string>
    ): SavedPanel | null => {
        for (const [key, message] of Object.entries(misplaced)) {
            if (key in panel) {
                problems.push({ path: `${path}.${key}`, message })
            }
        }
        const spec = findPanel(panels, panel.type)
        if (!spec) {
            problems.push({
                path: `${path}.type`,
                message: `Unknown panel type "${panel.type}". Known types: ${panels.map((known) => known.type).join(', ')}`,
            })
            return null
        }
        const fields = schema.safeParse(panel)
        if (!fields.success) {
            problems.push(...issuesAt(path, fields.error))
        }
        const configError = spec.configError(panel.config)
        if (configError) {
            problems.push(...issuesAt(`${path}.config`, configError))
        }
        return fields.success && !configError ? fields.data : null
    }

    const shared = new Map(
        Object.entries(parsed.data.panels ?? {}).map(([key, panel]) => [
            key,
            checkContent(panel, `panels.${key}`, sharedPanelSchema, ON_SHARED_PANEL),
        ])
    )

    // A panel's size can depend on its config, so it is only worked out from a valid one.
    const checkSize = (panel: SavedPanel | null, tile: TileHead, tilePath: string): void => {
        if (!panel) {
            return
        }
        const size = sizeOf(panel)
        if (tile.place.w < size.minW || tile.place.h < size.minH) {
            problems.push({
                path: `${tilePath}.place`,
                message: `This ${panel.type} tile is at least ${size.minW} columns wide and ${size.minH} rows tall`,
            })
        }
    }

    const checkGrid = (tiles: TileHead[], cols: number, path: string, depth: number): void => {
        tiles.forEach((tile, index) => {
            const tilePath = `${path}[${index}]`
            if (seenIds.has(tile.id)) {
                problems.push({ path: `${tilePath}.id`, message: `The id "${tile.id}" is used by another tile or tab` })
            }
            seenIds.add(tile.id)
            if (tile.place.x + tile.place.w > cols) {
                problems.push({ path: `${tilePath}.place`, message: `The tile goes past the grid's ${cols} columns` })
            }

            if (!('type' in tile.panel)) {
                const { ref } = tile.panel
                for (const [key, message] of Object.entries(ON_PANEL_REF)) {
                    if (key in tile.panel) {
                        problems.push({ path: `${tilePath}.panel.${key}`, message })
                    }
                }
                if (!shared.has(ref)) {
                    problems.push({
                        path: `${tilePath}.panel.ref`,
                        message: `There is no panel "${ref}" in the dashboard's panels`,
                    })
                }
                checkSize(shared.get(ref) ?? null, tile, tilePath)
                return
            }

            if (tile.panel.type === 'section') {
                if (depth >= MAX_SECTION_DEPTH) {
                    problems.push({
                        path: `${tilePath}.panel`,
                        message: `Sections nest at most ${MAX_SECTION_DEPTH} deep`,
                    })
                    return
                }
                const section = sectionHeadSchema.safeParse(tile.panel)
                if (!section.success) {
                    problems.push(...issuesAt(`${tilePath}.panel`, section.error))
                    return
                }
                checkGrid(section.data.tiles, tile.place.w, `${tilePath}.panel.tiles`, depth + 1)
                return
            }

            const panel = checkContent(
                tile.panel as PanelHead,
                `${tilePath}.panel`,
                documentContentPanelSchema,
                ON_CONTENT_PANEL
            )
            checkSize(panel, tile, tilePath)
        })
    }

    const filterIds = new Set<string>()
    const validFilters: Omit<SavedFilter, 'id'>[] = []
    parsed.data.filters?.forEach((filter, index) => {
        const path = `filters[${index}]`
        if (filterIds.has(filter.id)) {
            problems.push({ path: `${path}.id`, message: `The id "${filter.id}" is used by another filter` })
        }
        filterIds.add(filter.id)
        const spec = findFilterType(filters, filter.type)
        if (!spec) {
            problems.push({
                path: `${path}.type`,
                message: `Unknown filter type "${filter.type}". Known types: ${filters.map((known) => known.type).join(', ')}`,
            })
            return
        }
        const config = spec.configSchema.safeParse(filter.config)
        if (!config.success) {
            problems.push(...issuesAt(`${path}.config`, config.error))
            return
        }
        if (hasFilterOn(validFilters, filter, filters)) {
            problems.push({ path, message: 'Another filter already narrows this field' })
        }
        validFilters.push(filter)
    })

    parsed.data.tabs.forEach((tab, index) => {
        if (seenIds.has(tab.id)) {
            problems.push({ path: `tabs[${index}].id`, message: `The id "${tab.id}" is used by another tile or tab` })
        }
        seenIds.add(tab.id)
        // Parsing keeps only the fields of the first kind of tab that fits, so the other kind's are checked here.
        const rawTab = (document as { tabs: object[] }).tabs[index]
        if ('tiles' in rawTab && 'href' in rawTab) {
            problems.push({ path: `tabs[${index}]`, message: 'A tab holds tiles or links somewhere else, not both' })
        }
        if ('tiles' in tab) {
            checkGrid(tab.tiles, GRID.columns, `tabs[${index}].tiles`, 0)
        }
    })
    return problems
}
