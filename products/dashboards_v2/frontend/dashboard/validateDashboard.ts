import { z } from 'zod'

import { type PanelSpec, findPanel, sizeOfPanels } from '../panels/panelSpec'
import {
    dashboardDocumentSchema,
    documentContentPanelSchema,
    gridTabSchema,
    linkTabSchema,
    ONE_GRID_TAB,
    sectionPanelSchema,
    sharedPanelSchema,
    tileSchema,
    panelRefSchema,
} from './dashboardSchema'
import { type ContentPanel, GRID } from './dashboardTypes'

// Deeper than anyone builds by hand, and shallow enough that walking a hostile document cannot overflow the stack.
export const MAX_SECTION_DEPTH = 10

export interface DashboardProblem {
    /** Where the problem is, such as `tabs[0].tiles[2].panel.config.query`. */
    path: string
    message: string
}

// The document schemas, with each panel checked only for a `type` at first. A panel's fields depend on its type, so
// the walk below checks each one against the schema for that type, which gives a clearer problem than a failed union.
const panelHeadSchema = z.looseObject({ type: z.string() })
type PanelHead = z.infer<typeof panelHeadSchema>
const tileHeadSchema = tileSchema.extend({ panel: z.union([panelHeadSchema, panelRefSchema]) })
type TileHead = z.infer<typeof tileHeadSchema>
const sectionHeadSchema = sectionPanelSchema.extend({ tiles: z.array(tileHeadSchema) })
const dashboardHeadSchema = dashboardDocumentSchema.extend({
    panels: z.record(z.string(), panelHeadSchema).optional(),
    tabs: z
        .array(z.union([gridTabSchema.extend({ tiles: z.array(tileHeadSchema) }), linkTabSchema]))
        .refine((tabs) => tabs.some((tab) => 'tiles' in tab), ONE_GRID_TAB),
})

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
 * or a saved dashboard from the API. `panels` are the types the host can show. An empty result means it is valid.
 * Overlaps and gaps are not problems, because loading the dashboard settles them.
 */
export function validateDashboard(document: unknown, panels: PanelSpec[]): DashboardProblem[] {
    const parsed = dashboardHeadSchema.safeParse(document)
    if (!parsed.success) {
        return issuesAt('', parsed.error)
    }
    const problems: DashboardProblem[] = []
    const sizeOf = sizeOfPanels(panels)
    const seenIds = new Set<string>()

    const checkContent = (panel: PanelHead, path: string, schema: z.ZodType): ContentPanel | null => {
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
        const config = spec.configSchema.safeParse(panel.config)
        if (!config.success) {
            problems.push(...issuesAt(`${path}.config`, config.error))
            return null
        }
        return { ...panel, config: config.data } as ContentPanel
    }

    const shared = new Map(
        Object.entries(parsed.data.panels ?? {}).map(([key, panel]) => [
            key,
            checkContent(panel, `panels.${key}`, sharedPanelSchema),
        ])
    )

    // A panel's size can depend on its config, so it is only worked out from a valid one.
    const checkSize = (panel: ContentPanel | null, tile: TileHead, tilePath: string): void => {
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

            const panel = checkContent(tile.panel, `${tilePath}.panel`, documentContentPanelSchema)
            checkSize(panel, tile, tilePath)
        })
    }

    parsed.data.tabs.forEach((tab, index) => {
        if (seenIds.has(tab.id)) {
            problems.push({ path: `tabs[${index}].id`, message: `The id "${tab.id}" is used by another tile or tab` })
        }
        seenIds.add(tab.id)
        if ('tiles' in tab) {
            checkGrid(tab.tiles, GRID.columns, `tabs[${index}].tiles`, 0)
        }
    })
    return problems
}
