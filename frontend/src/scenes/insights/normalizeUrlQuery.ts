import { isObject } from 'lib/utils/guards'

import { Node, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

/** Shapes we repair, reported as-is to telemetry. */
export type UrlQueryRepair = 'display' | 'series_breakdown'

const VALID_DISPLAYS = new Set<string>(Object.values(ChartDisplayType))

/**
 * Short forms of every `ChartDisplayType`, so a query that asks for `Line` or `Table` still opens.
 * The insight editor writes the full value, but a query composed by hand or by a model often uses
 * the short label instead, and the API then rejects the whole query.
 */
const DISPLAY_ALIASES = new Map<string, ChartDisplayType>([
    // The two values whose short label drops a whole word, which the loop below cannot derive.
    ['number', ChartDisplayType.BoldNumber],
    ['map', ChartDisplayType.WorldMap],
])

for (const display of Object.values(ChartDisplayType)) {
    const lowercased = display.toLowerCase()
    const withoutPrefix = lowercased.replace(/^actions/, '')
    for (const alias of [lowercased, withoutPrefix, withoutPrefix.replace(/graph$/, '')]) {
        if (alias && !DISPLAY_ALIASES.has(alias)) {
            DISPLAY_ALIASES.set(alias, display)
        }
    }
}

/** Breakdown keys that belong on the query source, not on a series entry. */
const BREAKDOWN_KEYS = [
    'breakdown',
    'breakdown_type',
    'breakdowns',
    'breakdown_group_type_index',
    'breakdown_limit',
    'breakdown_hide_other_aggregation',
    'breakdown_histogram_bin_count',
    'breakdown_normalize_url',
]

/** Where a `ChartDisplayType` sits inside a query source. `DataVisualizationNode` holds its own. */
const DISPLAY_FILTER_KEYS = ['trendsFilter', 'stickinessFilter']

/** The kinds that take both `series` and `breakdownFilter`. */
const BREAKDOWN_SOURCE_KINDS = new Set<string>([NodeKind.TrendsQuery, NodeKind.FunnelsQuery])

/**
 * Repairs the legacy and near-miss shapes we see in `#q=` links before the query reaches the API,
 * which rejects the whole query on the first unknown field or value. A value that is not a query
 * node at all returns `null`, because there is nothing to run.
 */
export function normalizeUrlQuery(query: unknown): { query: Node | null; repairs: UrlQueryRepair[] } {
    if (!isObject(query) || typeof query.kind !== 'string') {
        return { query: null, repairs: [] }
    }
    const repairs = new Set<UrlQueryRepair>()
    return { query: normalizeNode(query, repairs) as Node, repairs: [...repairs] }
}

function normalizeNode(node: unknown, repairs: Set<UrlQueryRepair>): unknown {
    if (Array.isArray(node)) {
        return node.map((entry) => normalizeNode(entry, repairs))
    }
    if (!isObject(node)) {
        return node
    }

    const normalized: Record<string, any> = {}
    for (const [key, value] of Object.entries(node)) {
        normalized[key] = normalizeNode(value, repairs)
    }

    if (normalized.kind === NodeKind.DataVisualizationNode) {
        repairDisplay(normalized, repairs)
    }
    for (const key of DISPLAY_FILTER_KEYS) {
        if (isObject(normalized[key])) {
            repairDisplay(normalized[key] as Record<string, any>, repairs)
        }
    }

    if (Array.isArray(normalized.series) && BREAKDOWN_SOURCE_KINDS.has(normalized.kind)) {
        hoistSeriesBreakdown(normalized, repairs)
    }

    return normalized
}

function repairDisplay(holder: Record<string, any>, repairs: Set<UrlQueryRepair>): void {
    const display = holder.display
    if (typeof display !== 'string' || VALID_DISPLAYS.has(display)) {
        return
    }
    const lowercased = display.toLowerCase()
    const alias = DISPLAY_ALIASES.get(lowercased) ?? DISPLAY_ALIASES.get(lowercased.replace(/^actions/, ''))
    if (alias) {
        holder.display = alias
    } else {
        // No alias fits, so drop the value and let the insight fall back to its default chart.
        delete holder.display
    }
    repairs.add('display')
}

function hoistSeriesBreakdown(source: Record<string, any>, repairs: Set<UrlQueryRepair>): void {
    const hoisted: Record<string, any> = {}
    let found = false

    source.series = source.series.map((entry: unknown) => {
        if (!isObject(entry)) {
            return entry
        }
        const series = { ...entry }
        for (const key of BREAKDOWN_KEYS) {
            if (key in series) {
                found = true
                if (series[key] != null && !(key in hoisted)) {
                    hoisted[key] = series[key]
                }
                delete series[key]
            }
        }
        return series
    })

    if (found) {
        // A breakdown the source already declares is the one the user means, so it wins.
        source.breakdownFilter = { ...hoisted, ...(isObject(source.breakdownFilter) ? source.breakdownFilter : {}) }
        repairs.add('series_breakdown')
    }
}
