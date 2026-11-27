import type { ComponentType } from 'react'
import { z } from 'zod'

import type { DataFrame } from '../../query/queryTypes'
import { type PanelSize } from '../core/panelSpec'

/** The options of a kind of chart that has none. */
export const NO_OPTIONS = z.strictObject({})

export type NoOptions = z.infer<typeof NO_OPTIONS>

/** One kind of chart, without its component, so code outside the browser can load it. */
export type VizSpec<Options = unknown> = {
    /** Matches `config.viz.type` on the charts it draws. */
    type: string
    label: string
    size: PanelSize
    /** The shape of `config.viz.options`. Missing options are `{}`. */
    optionsSchema: z.ZodType<Options>
}

/**
 * What a chart shows before it has rows to draw. Each one is optional: a kind of chart can set its own, the host can
 * set defaults for every chart with `createChartPanel`, and the chart panel has built-in ones for the rest. The
 * built-in kinds of chart set a skeleton shaped like the chart, which a host's `states.Loading` replaces.
 */
export type ChartStates<Options = unknown> = {
    Loading?: ComponentType<{ options: Options }>
    Empty?: ComponentType<{ options: Options }>
    Error?: ComponentType<{ message: string; options: Options }>
    /** Shown while the host has no real data. By default, the chart is drawn from made-up frames with a "Sample data" tag. */
    SampleData?: ComponentType<{ options: Options }>
    /** Whether a result has nothing to draw. By default, a result is empty when no frame has any values. */
    isEmpty?: (frames: DataFrame[]) => boolean
}

export type VizDefinition<Options = unknown> = VizSpec<Options> &
    ChartStates<Options> & {
        /** Draws a query result that has rows. Loading, errors and empty results come from `ChartStates`. */
        Component: ComponentType<{ frames: DataFrame[]; options: Options }>
    }

/** Puts a kind of chart with its own options type into a list. A chart is only drawn by the kind it names. */
export function defineViz<Options>(viz: VizDefinition<Options>): VizDefinition {
    return viz as unknown as VizDefinition
}
