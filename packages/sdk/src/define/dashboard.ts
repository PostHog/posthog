import type { DashboardsCreateInput } from '../generated/api.js'
import type { JsonValue } from '../types.js'
import { type Definition, defineKind, isDefinition, isRef, type Ref } from './definition.js'
import { type InsightDefinition, type InsightInput } from './insight.js'

export interface TileLayout {
    x: number
    y: number
    w: number
    h: number
    // Other grid fields, such as `minW`, `minH` or `i`, pass through as written, and check warns
    // that PostHog keeps only x, y, w and h.
    [field: string]: JsonValue
}

// The API's shape: one layout per breakpoint, `sm` for desktop and `xs` for mobile.
export interface TileLayouts {
    sm?: TileLayout
    xs?: TileLayout
}

export interface InsightTile {
    insight: InsightDefinition | Ref<'insight'>
    layouts?: TileLayouts
    color?: string
    show_description?: boolean
}

export interface TextTile {
    text: { body: string }
    layouts?: TileLayouts
    color?: string
}

export type Tile = InsightTile | TextTile

// An insight written inline as a tile, keyed by the dashboard key plus the tile key, so moving the
// tile keeps the insight it made.
export interface InlineInsightTile extends Omit<InsightTile, 'insight'> {
    insight: InsightInput
    key?: string
}

export type TileInput = Tile | InlineInsightTile | InsightDefinition | InsightInput

export interface TileOptions {
    // Names the insight a tile makes from an inline insight. Defaults to a slug of the insight's name.
    key?: string
    layouts?: TileLayouts
    color?: string
    show_description?: boolean
}

export function tile(
    insight: InsightDefinition | Ref<'insight'> | InsightInput,
    { key, ...options }: TileOptions = {}
): InsightTile | InlineInsightTile {
    if (isDefinition(insight) || isRef(insight)) {
        return { insight, ...options }
    }
    return { insight, ...options, ...(key !== undefined ? { key } : {}) }
}

export function text(body: string, options: { layouts?: TileLayouts; color?: string } = {}): TextTile {
    return { text: { body }, ...options }
}

// Fields that are steps of a create call, not part of a dashboard.
type CreateSteps = 'use_template' | 'use_dashboard' | 'delete_insights'

export interface DashboardInput extends Omit<DashboardsCreateInput, CreateSteps> {
    tiles?: readonly TileInput[]
}

export interface DashboardBody extends Omit<DashboardsCreateInput, CreateSteps> {
    tiles: Tile[]
}

export type DashboardDefinition<Key extends string = string> = Definition<'dashboard', Key, DashboardBody>

export function dashboard<const Key extends string>(key: Key, input: DashboardInput): DashboardDefinition<Key> {
    const { tiles = [], ...fields } = input
    const resolved = tiles.map((entry, index) => resolveTile(key, entry, index))
    return defineKind('dashboard', key, { ...fields, tiles: withDefaultLayouts(resolved) })
}

function isInsightInput(value: TileInput): value is InsightInput {
    return !isDefinition(value) && 'query' in value
}

function resolveTile(dashboardKey: string, entry: TileInput, index: number): Tile {
    if (isDefinition(entry)) {
        return { insight: entry as InsightDefinition }
    }
    if (isInsightInput(entry)) {
        return { insight: inlineInsight(dashboardKey, entry, undefined, index) }
    }
    if ('text' in entry) {
        return entry
    }
    const { insight, ...rest } = entry
    if (
        insight === null ||
        typeof insight !== 'object' ||
        isDefinition(insight) ||
        isRef(insight) ||
        !('query' in insight)
    ) {
        // Anything that is not an inline insight goes through as written, for check to report.
        return { insight, ...rest } as InsightTile
    }
    const { key, ...layout } = rest as Omit<InlineInsightTile, 'insight'>
    return { insight: inlineInsight(dashboardKey, insight, key, index), ...layout }
}

function slug(name: string): string {
    return name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '')
}

function inlineInsight(
    dashboardKey: string,
    body: InsightInput,
    tileKey: string | undefined,
    index: number
): InsightDefinition {
    const ownKey = tileKey ?? (typeof body.name === 'string' ? slug(body.name) : '')
    return defineKind('insight', ownKey ? `${dashboardKey}-${ownKey}` : '', body, {
        dashboard: dashboardKey,
        tile: tileKey ?? String(index),
    })
}

const GRID_COLUMNS = 12
const DEFAULT_SIZE = { insight: { w: 6, h: 5 }, text: { w: GRID_COLUMNS, h: 2 } }

// Tiles without a layout flow left to right, two insights to a row, below every tile that has one.
function withDefaultLayouts(tiles: Tile[]): Tile[] {
    let top = 0
    for (const { layouts } of tiles) {
        if (layouts?.sm) {
            top = Math.max(top, layouts.sm.y + layouts.sm.h)
        }
    }
    let x = 0
    let rowHeight = 0
    return tiles.map((entry) => {
        if (entry.layouts?.sm) {
            return entry
        }
        const { w, h } = 'text' in entry ? DEFAULT_SIZE.text : DEFAULT_SIZE.insight
        if (x + w > GRID_COLUMNS) {
            top += rowHeight
            x = 0
            rowHeight = 0
        }
        const placed = { ...entry, layouts: { ...entry.layouts, sm: { x, y: top, w, h } } }
        x += w
        rowHeight = Math.max(rowHeight, h)
        return placed
    })
}
