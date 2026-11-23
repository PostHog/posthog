import type { JsonObject, JsonValue } from '../types.js'
import { isRefValue } from './description.js'

export interface TileIssue {
    code: string
    path: string
    message: string
    severity?: 'error' | 'warning'
}

const TILE_FIELDS = ['insight', 'text', 'layouts', 'color', 'show_description']
const BREAKPOINTS = ['sm', 'xs']
const POSITION = { x: 0, y: 0, w: 1, h: 1 }
const GRID_COLUMNS = 12
// Grid fields a dashboard editor writes besides the position. PostHog validates a tile's layout
// with `DashboardPatchTileLayoutBoxSerializer`, which keeps only x, y, w and h, so these are
// accepted, typed, and reported as not kept.
const GRID_FIELDS: Readonly<Record<string, 'number' | 'boolean' | 'string'>> = {
    i: 'string',
    minW: 'number',
    minH: 'number',
    maxW: 'number',
    maxH: 'number',
    moved: 'boolean',
    static: 'boolean',
}

function listText(names: readonly string[]): string {
    return names.length <= 1 ? (names[0] ?? '') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

const isObject = (value: JsonValue | undefined): value is JsonObject =>
    typeof value === 'object' && value !== null && !Array.isArray(value)

function layoutIssues(layouts: JsonValue, at: string): TileIssue[] {
    if (!isObject(layouts)) {
        return [{ code: 'tile_invalid', path: at, message: `${at} must be an object with sm and xs layouts.` }]
    }
    const issues: TileIssue[] = []
    for (const [breakpoint, layout] of Object.entries(layouts)) {
        const where = `${at}.${breakpoint}`
        if (!BREAKPOINTS.includes(breakpoint)) {
            issues.push({
                code: 'unknown_field',
                path: where,
                message: `${where} is not a breakpoint. A tile has sm and xs layouts.`,
            })
            continue
        }
        if (!isObject(layout)) {
            issues.push({ code: 'tile_invalid', path: where, message: `${where} must be an object.` })
            continue
        }
        for (const [name, minimum] of Object.entries(POSITION)) {
            const value = layout[name]
            if (typeof value !== 'number' || !Number.isInteger(value) || value < minimum) {
                issues.push({
                    code: 'tile_invalid',
                    path: `${where}.${name}`,
                    message: `${where}.${name} must be a whole number of at least ${minimum}.`,
                })
            }
        }
        const { x, w } = layout
        if (
            breakpoint === 'sm' &&
            typeof x === 'number' &&
            typeof w === 'number' &&
            Number.isInteger(x) &&
            Number.isInteger(w) &&
            x + w > GRID_COLUMNS
        ) {
            issues.push({
                code: 'tile_invalid',
                path: where,
                message: `${where} must fit the ${GRID_COLUMNS}-column grid: x plus w is ${x + w}.`,
            })
        }
        const dropped = Object.keys(layout)
            .filter((name) => name in GRID_FIELDS)
            .sort()
        if (dropped.length > 0) {
            issues.push({
                code: 'layout_field_dropped',
                severity: 'warning',
                path: where,
                message: `${where} sets ${listText(dropped)}, which PostHog does not keep: a tile's layout stores only x, y, w and h.`,
            })
        }
        for (const [name, value] of Object.entries(layout)) {
            if (name in POSITION) {
                continue
            }
            const type = GRID_FIELDS[name]
            if (!type) {
                issues.push({
                    code: 'unknown_field',
                    path: `${where}.${name}`,
                    message: `${where}.${name} is not a layout field. Remove it, or check its spelling.`,
                })
            } else if (typeof value !== type) {
                issues.push({
                    code: 'tile_invalid',
                    path: `${where}.${name}`,
                    message: `${where}.${name} must be a ${type}.`,
                })
            }
        }
    }
    return issues
}

// A dashboard's tiles as the description carries them: one insight or one text, a layout per
// breakpoint, and an optional color and description switch.
export function tileIssues(tiles: JsonValue | undefined): TileIssue[] {
    if (tiles === undefined) {
        return []
    }
    if (!Array.isArray(tiles)) {
        return [{ code: 'tile_invalid', path: 'tiles', message: 'tiles must be a list.' }]
    }
    const issues: TileIssue[] = []
    tiles.forEach((tile, position) => {
        const at = `tiles[${position}]`
        if (!isObject(tile)) {
            issues.push({ code: 'tile_invalid', path: at, message: `${at} must be an object.` })
            return
        }
        const hasInsight = tile.insight !== undefined
        const hasText = tile.text !== undefined
        if (hasInsight === hasText) {
            issues.push({
                code: 'tile_invalid',
                path: at,
                message: `${at} must show either an insight or text, and shows ${hasInsight ? 'both' : 'neither'}.`,
            })
        }
        if (hasText && (!isObject(tile.text) || typeof tile.text.body !== 'string')) {
            issues.push({
                code: 'tile_invalid',
                path: `${at}.text`,
                message: `${at}.text must be { body } with the Markdown text.`,
            })
        }
        if (tile.layouts !== undefined) {
            issues.push(...layoutIssues(tile.layouts, `${at}.layouts`))
        }
        if (
            tile.color !== undefined &&
            tile.color !== null &&
            !isRefValue(tile.color) &&
            (typeof tile.color !== 'string' || tile.color.length > 400)
        ) {
            issues.push({
                code: 'tile_invalid',
                path: `${at}.color`,
                message: `${at}.color must be a color name of at most 400 characters.`,
            })
        }
        if (
            tile.show_description !== undefined &&
            tile.show_description !== null &&
            typeof tile.show_description !== 'boolean'
        ) {
            issues.push({
                code: 'tile_invalid',
                path: `${at}.show_description`,
                message: `${at}.show_description must be true or false.`,
            })
        }
        for (const name of Object.keys(tile)) {
            if (!TILE_FIELDS.includes(name)) {
                issues.push({
                    code: 'unknown_field',
                    path: `${at}.${name}`,
                    message: `${at}.${name} is not a field of a tile. A tile takes ${TILE_FIELDS.join(', ')}.`,
                })
            }
        }
    })
    return issues
}
