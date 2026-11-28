import { z } from 'zod'

import { timeRangeSchema, type TimeRange } from '../../filters/time/timeRangeSchema'
import { type PanelQuery, panelQuerySchema } from '../../query/querySchema'
import { UNKNOWN_PANEL_SIZE, type PanelSpec } from '../core/panelSpec'
import { areaSpec } from './viz/area/areaSpec'
import { barSpec } from './viz/bar/barSpec'
import { barListSpec } from './viz/barList/barListSpec'
import { boxPlotSpec } from './viz/boxPlot/boxPlotSpec'
import { comboSpec } from './viz/combo/comboSpec'
import { flameGraphSpec } from './viz/flameGraph/flameGraphSpec'
import { funnelSpec } from './viz/funnel/funnelSpec'
import { gaugeSpec } from './viz/gauge/gaugeSpec'
import { heatmapSpec } from './viz/heatmap/heatmapSpec'
import { lineSpec } from './viz/line/lineSpec'
import { metricSpec } from './viz/metric/metricSpec'
import { pieSpec } from './viz/pie/pieSpec'
import { proportionSpec } from './viz/proportion/proportionSpec'
import { sankeySpec } from './viz/sankey/sankeySpec'
import { scatterSpec } from './viz/scatter/scatterSpec'
import { slopeSpec } from './viz/slope/slopeSpec'
import type { VizSpec } from './vizTypes'

/** One of the queries a chart draws together, such as a latency series next to the deploys that explain it. */
export type ChartTarget = {
    refId: string
    query: PanelQuery
    /** Names each series the query returns. `{{label}}` is replaced with that series' value of `label`. */
    legend?: string
    project?: number
}

export type ChartConfig = {
    query?: PanelQuery
    targets?: ChartTarget[]
    /** The id of the project the chart's queries read. Left out, the project of the page that shows the dashboard. */
    project?: number
    /** How the result is drawn. Changing it never changes the data. */
    viz: { type: string; options?: unknown }
    /** Overrides the time range around the chart, such as the dashboard's. */
    time?: TimeRange
}

// Every target is a query the moment its tile mounts, so a cap keeps one tile from flooding the query batch.
const MAX_CHART_TARGETS = 26

const chartTargetSchema = z.strictObject({
    // The query batch endpoint rejects a longer refId or legend, and with it every other tile's query in the batch.
    refId: z.string().min(1).max(200),
    query: panelQuerySchema,
    legend: z.string().max(1000).optional(),
    project: z.int().positive().optional(),
})

// PromQL and LogQL text carries no range, so without one around the chart the query has no window to run on.
export function hasNoOwnRange(target: ChartTarget): boolean {
    return target.query.language === 'promql' || target.query.language === 'logql'
}

export function chartTargets(config: ChartConfig): ChartTarget[] {
    if (config.targets) {
        return config.targets
    }
    return config.query ? [{ refId: 'A', query: config.query }] : []
}

/** A panel that runs one query and draws it as one of `vizTypes`. The tile's "Chart type" menu switches the kind. */
export function chartSpec(vizTypes: VizSpec[]): PanelSpec<ChartConfig, 'chart'> {
    const vizSchemas = vizTypes.map((viz) =>
        // Missing options are read as `{}`, so they are checked as `{}` too.
        z.strictObject({
            type: z.literal(viz.type),
            options: z.preprocess((options) => options ?? {}, viz.optionsSchema),
        })
    )
    return {
        type: 'chart',
        size: UNKNOWN_PANEL_SIZE,
        sizeFor: (panel) => vizTypes.find((viz) => viz.type === panel.config?.viz?.type)?.size ?? UNKNOWN_PANEL_SIZE,
        configSchema: z
            .strictObject({
                query: panelQuerySchema.optional(),
                targets: z.array(chartTargetSchema).min(1).max(MAX_CHART_TARGETS).optional(),
                project: z.int().positive().optional(),
                // Documents saved before the rename still say `stat`.
                viz: z.preprocess(
                    (viz) =>
                        viz && typeof viz === 'object' && (viz as { type?: unknown }).type === 'stat'
                            ? { ...viz, type: 'metric' }
                            : viz,
                    vizSchemas.length > 0 ? z.union(vizSchemas) : z.never()
                ),
                time: timeRangeSchema.optional(),
            })
            .refine((config) => (config.query === undefined) !== (config.targets === undefined), {
                message: 'A chart needs either a query or a list of targets, not both',
                path: ['query'],
            })
            .refine(
                (config) =>
                    new Set(config.targets?.map((target) => target.refId)).size === (config.targets?.length ?? 0),
                { message: "Each of a chart's targets needs its own refId", path: ['targets'] }
            ),
        allowedCustomizations: ['backgroundColor'],
    }
}

/** Every built-in kind of chart, without components, so code outside the browser can validate a document. */
export const BUILT_IN_VIZ_SPECS = [
    metricSpec,
    lineSpec,
    barSpec,
    areaSpec,
    comboSpec,
    pieSpec,
    barListSpec,
    proportionSpec,
    funnelSpec,
    gaugeSpec,
    heatmapSpec,
    scatterSpec,
    boxPlotSpec,
    slopeSpec,
    sankeySpec,
    flameGraphSpec,
] as VizSpec[]
