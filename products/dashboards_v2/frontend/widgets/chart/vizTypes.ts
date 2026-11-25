import type { ComponentType } from 'react'
import type { z } from 'zod'

import type { WidgetQuery } from '../../dashboard/dashboardSchema'
import type { TimeRange, WidgetSize } from '../../dashboard/dashboardTypes'

export type { WidgetQuery }

/** A query's result in one shape every kind of chart reads, so a chart can switch kind without running its query again. */
export interface DataFrame {
    name?: string
    refId?: string
    fields: {
        name: string
        type: 'time' | 'number' | 'string' | 'boolean' | 'other'
        values: unknown[]
        unit?: string
    }[]
}

/** What a chart asks the host's runner to run. The time range is the chart's own, or the one around it. */
export interface QueryRequest {
    query: WidgetQuery
    time: TimeRange
    legend?: string
}

/** A query's frames, and how fresh they are when the host's runner knows it, such as from a cached result. */
export interface QueryResult {
    frames: DataFrame[]
    /** When the result was computed, as an ISO timestamp. */
    fetchedAt?: string
    /** True when the result is older than its query's refresh interval, so a newer one may be on its way. */
    stale?: boolean
}

/** Runs a chart's query and returns its result. The host supplies it, so the dashboard never fetches data itself. */
export type RunQuery = (request: QueryRequest) => Promise<QueryResult>

/** One kind of chart, without its component, so code outside the browser can load it. */
export interface VizSpec<Options = unknown> {
    /** Matches `config.viz.type` on the charts it draws. */
    type: string
    /** The name the add menu shows. */
    label: string
    size: WidgetSize
    /** The shape of `config.viz.options`. Missing options are `{}`. */
    optionsSchema: z.ZodType<Options>
}

/**
 * What a chart shows before it has rows to draw. Each one is optional: a kind of chart can set its own, the host can
 * set defaults for every chart with `createChartWidget`, and the chart widget has built-in ones for the rest. The
 * built-in kinds of chart set a skeleton shaped like the chart, which a host's `states.Loading` replaces.
 */
export interface ChartStates<Options = unknown> {
    Loading?: ComponentType<{ options: Options }>
    Empty?: ComponentType<{ options: Options }>
    Error?: ComponentType<{ message: string; options: Options }>
    /** Whether a result has nothing to draw. By default, a result is empty when no frame has any values. */
    isEmpty?: (frames: DataFrame[]) => boolean
}

export interface VizDefinition<Options = unknown> extends VizSpec<Options>, ChartStates<Options> {
    /** Draws a query result that has rows. Loading, errors and empty results come from `ChartStates`. */
    Component: ComponentType<{ frames: DataFrame[]; options: Options }>
}

/** Puts a kind of chart with its own options type into a list. A chart is only drawn by the kind it names. */
export function defineViz<Options>(viz: VizDefinition<Options>): VizDefinition {
    return viz as unknown as VizDefinition
}
