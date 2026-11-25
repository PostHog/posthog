import { z } from 'zod'

import { type WidgetSpec, findWidget, sizeOfWidgets } from '../widgets/widgetSpec'
import {
    contentWidgetSchema,
    dashboardSchema,
    gridTabSchema,
    linkTabSchema,
    ONE_GRID_TAB,
    sectionWidgetSchema,
    tileSchema,
} from './dashboardSchema'
import { type ContentWidget, GRID } from './dashboardTypes'

// Deeper than anyone builds by hand, and shallow enough that walking a hostile document cannot overflow the stack.
export const MAX_SECTION_DEPTH = 10

export interface DashboardProblem {
    /** Where the problem is, such as `tabs[0].tiles[2].widget.config.query`. */
    path: string
    message: string
}

// The document schemas, with each widget checked only for a `type` at first. A widget's fields depend on its type, so
// the walk below checks each one against the schema for that type, which gives a clearer problem than a failed union.
const tileHeadSchema = tileSchema.extend({ widget: z.looseObject({ type: z.string() }) })
type TileHead = z.infer<typeof tileHeadSchema>
const sectionHeadSchema = sectionWidgetSchema.extend({ tiles: z.array(tileHeadSchema) })
const dashboardHeadSchema = dashboardSchema.extend({
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
 * or a saved dashboard from the API. `widgets` are the types the host can show. An empty result means it is valid.
 * Overlaps and gaps are not problems, because loading the dashboard settles them.
 */
export function validateDashboard(document: unknown, widgets: WidgetSpec[]): DashboardProblem[] {
    const parsed = dashboardHeadSchema.safeParse(document)
    if (!parsed.success) {
        return issuesAt('', parsed.error)
    }
    const problems: DashboardProblem[] = []
    const sizeOf = sizeOfWidgets(widgets)
    const seenIds = new Set<string>()

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

            if (tile.widget.type === 'section') {
                if (depth >= MAX_SECTION_DEPTH) {
                    problems.push({
                        path: `${tilePath}.widget`,
                        message: `Sections nest at most ${MAX_SECTION_DEPTH} deep`,
                    })
                    return
                }
                const section = sectionHeadSchema.safeParse(tile.widget)
                if (!section.success) {
                    problems.push(...issuesAt(`${tilePath}.widget`, section.error))
                    return
                }
                checkGrid(section.data.tiles, tile.place.w, `${tilePath}.widget.tiles`, depth + 1)
                return
            }

            const widget = findWidget(widgets, tile.widget.type)
            if (!widget) {
                problems.push({
                    path: `${tilePath}.widget.type`,
                    message: `Unknown widget type "${tile.widget.type}". Known types: ${widgets.map((known) => known.type).join(', ')}`,
                })
                return
            }
            const fields = contentWidgetSchema.safeParse(tile.widget)
            if (!fields.success) {
                problems.push(...issuesAt(`${tilePath}.widget`, fields.error))
            }
            const config = widget.configSchema.safeParse(tile.widget.config)
            if (!config.success) {
                problems.push(...issuesAt(`${tilePath}.widget.config`, config.error))
            }
            // A widget's size can depend on its config, so it is only worked out from a valid one.
            if (config.success) {
                const size = sizeOf({ ...tile.widget, config: config.data } as ContentWidget)
                if (tile.place.w < size.minW || tile.place.h < size.minH) {
                    problems.push({
                        path: `${tilePath}.place`,
                        message: `This ${widget.type} tile is at least ${size.minW} columns wide and ${size.minH} rows tall`,
                    })
                }
            }
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
