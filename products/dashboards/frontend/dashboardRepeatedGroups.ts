import type { Layout, LayoutItem } from 'react-grid-layout'

import { BREAKPOINT_COLUMN_COUNTS } from 'scenes/dashboard/dashboardUtils'

import type { DashboardFilter, MetricsDashboardVariable, TileFilters } from '~/queries/schema/schema-general'
import type { DashboardLayoutSize, DashboardTile } from '~/types'

import type { DashboardGroupRepeatApi } from './generated/api.schemas'

/** Each copy runs its own queries, so a variable with many values must not flood the dashboard with them. */
export const MAX_REPEATED_COPIES = 30

type Layouts = Partial<Record<DashboardLayoutSize, Layout>>

/** The data node collection of a dashboard's repeated copies, so a dashboard refresh can reload them. */
export function repeatedCopiesCollectionKey(dashboardId: number | string): string {
    return `dashboard-repeats-${dashboardId}`
}

export interface RepeatedTileCopy {
    /** The grid item id of the copy. */
    key: string
    tile: DashboardTile
    value: string
    /** The dashboard filters, with the repeat variable set to `value`. */
    filters: DashboardFilter
}

export interface RepeatedGroupsInput {
    tiles: DashboardTile[]
    layouts: Layouts
    groupRepeats: Record<string, DashboardGroupRepeatApi> | undefined
    /** The dashboard filters, with the full definition of each metric variable. */
    filters: DashboardFilter
    options: Record<string, string[]>
}

export interface RepeatedGroups {
    /** The tiles that the grid shows as they are. The insight tiles of a repeated group are left out. */
    tiles: DashboardTile[]
    copies: RepeatedTileCopy[]
    layouts: Layouts
}

interface ActiveRepeat {
    repeat: DashboardGroupRepeatApi
    variable: MetricsDashboardVariable
    values: string[]
    tiles: DashboardTile[]
}

function repeatValues(variable: MetricsDashboardVariable, options: string[] | undefined): string[] {
    const current = variable.current
    const values = !current || current.all ? (options ?? []) : current.values
    return [...new Set(values)].slice(0, MAX_REPEATED_COPIES)
}

function copyKey(tile: DashboardTile, index: number): string {
    return `repeat-${tile.id}-${index}`
}

/** The tile's overrides win over the dashboard filters, as they do for the original tile. */
function tileFilters(filters: DashboardFilter, overrides: TileFilters | null | undefined): DashboardFilter {
    const { ignoreDashboardFilters, ...tileOwn } = overrides ?? {}
    // The query still needs the metric variables to fill in the `$name` references.
    const base: DashboardFilter = ignoreDashboardFilters ? { metricVariables: filters.metricVariables } : filters
    const set = Object.fromEntries(Object.entries(tileOwn).filter(([, value]) => value != null))
    return { ...base, ...set }
}

function withValue(filters: DashboardFilter, name: string, value: string): DashboardFilter {
    return {
        ...filters,
        metricVariables: filters.metricVariables?.map((variable) =>
            variable.name === name ? { ...variable, current: { values: [value] } } : variable
        ),
    }
}

function expandLayout(layout: Layout, cols: number, repeats: ActiveRepeat[]): Layout {
    let items: LayoutItem[] = layout.map((item) => ({ ...item }))
    // Top to bottom, so that the box of each group already includes the shift from the groups above it.
    const ordered = repeats
        .map((active) => ({ active, ids: new Set(active.tiles.map((tile) => String(tile.id))) }))
        .filter(({ ids }) => items.some((item) => ids.has(item.i)))
        .sort(
            (a, b) =>
                Math.min(...items.filter((item) => a.ids.has(item.i)).map((item) => item.y)) -
                Math.min(...items.filter((item) => b.ids.has(item.i)).map((item) => item.y))
        )
    for (const { active, ids } of ordered) {
        const originals = items.filter((item) => ids.has(item.i))
        const left = Math.min(...originals.map((item) => item.x))
        const top = Math.min(...originals.map((item) => item.y))
        const width = Math.max(...originals.map((item) => item.x + item.w)) - left
        const bottom = Math.max(...originals.map((item) => item.y + item.h))
        const height = bottom - top
        const perRow =
            active.repeat.direction === 'horizontal' ? Math.max(1, Math.floor((cols - left) / Math.max(width, 1))) : 1
        const extraHeight = (Math.ceil(active.values.length / perRow) - 1) * height
        const copies = active.values.flatMap((_, index) =>
            originals.map((item) => ({
                ...item,
                i: copyKey(active.tiles.find((tile) => String(tile.id) === item.i)!, index),
                x: item.x + (index % perRow) * width,
                y: item.y + Math.floor(index / perRow) * height,
            }))
        )
        items = [
            ...items
                .filter((item) => !ids.has(item.i))
                .map((item) => (item.y >= bottom ? { ...item, y: item.y + extraHeight } : item)),
            ...copies,
        ]
    }
    return items
}

/**
 * Repeats the insight tiles of each repeated group once for each selected value of its metric variable.
 * The copies are not saved. A group whose variable has no values yet keeps its original tiles.
 */
export function expandRepeatedGroups(input: RepeatedGroupsInput): RepeatedGroups {
    const { tiles, layouts, groupRepeats, filters, options } = input
    const repeats: ActiveRepeat[] = Object.entries(groupRepeats ?? {}).flatMap(([groupKey, repeat]) => {
        const variable = filters.metricVariables?.find((other) => other.name === repeat.variable && other.source)
        // A viewer without access gets the insight without its query, and the original tile shows the access state.
        const groupTiles = tiles.filter((tile) => tile.group_key === groupKey && tile.insight?.query)
        const values = variable ? repeatValues(variable, options[variable.name]) : []
        return variable && values.length && groupTiles.length ? [{ repeat, variable, values, tiles: groupTiles }] : []
    })
    if (!repeats.length) {
        return { tiles, copies: [], layouts }
    }

    const repeatedIds = new Set(repeats.flatMap((active) => active.tiles.map((tile) => tile.id)))
    const copies = repeats.flatMap((active) =>
        active.values.flatMap((value, index) =>
            active.tiles.map((tile) => ({
                key: copyKey(tile, index),
                tile,
                value,
                filters: withValue(tileFilters(filters, tile.filters_overrides), active.variable.name, value),
            }))
        )
    )
    const expandedLayouts: Layouts = Object.fromEntries(
        Object.entries(layouts).map(([size, layout]) => [
            size,
            layout ? expandLayout(layout, BREAKPOINT_COLUMN_COUNTS[size as DashboardLayoutSize], repeats) : layout,
        ])
    )
    return { tiles: tiles.filter((tile) => !repeatedIds.has(tile.id)), copies, layouts: expandedLayouts }
}
