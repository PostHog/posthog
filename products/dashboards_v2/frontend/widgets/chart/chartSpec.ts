import { z } from 'zod'

import { type WidgetQuery, timeRangeSchema, widgetQuerySchema } from '../../dashboard/dashboardSchema'
import type { TimeRange } from '../../dashboard/dashboardTypes'
import { UNKNOWN_WIDGET_SIZE, type WidgetSpec } from '../widgetSpec'
import type { VizSpec } from './vizTypes'

/** One of the queries a chart draws together, such as a latency series next to the deploys that explain it. */
export interface ChartTarget {
    refId: string
    query: WidgetQuery
    /** Names each series the query returns. `{{label}}` is replaced with that series' value of `label`. */
    legend?: string
}

export interface ChartConfig {
    query?: WidgetQuery
    targets?: ChartTarget[]
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
    query: widgetQuerySchema,
    legend: z.string().max(1000).optional(),
})

export function chartTargets(config: ChartConfig): ChartTarget[] {
    if (config.targets) {
        return config.targets
    }
    return config.query ? [{ refId: 'A', query: config.query }] : []
}

/**
 * A widget that runs one query and draws it as one of `vizTypes`. The add menu offers one "Chart" item, which starts
 * as a line chart, and the tile's "Chart type" menu switches it to any other kind.
 */
export function chartSpec(vizTypes: VizSpec[]): WidgetSpec<ChartConfig> {
    const firstType = vizTypes.find((viz) => viz.type === 'line')?.type ?? vizTypes[0]?.type ?? 'line'
    const vizSchemas = vizTypes.map((viz) =>
        // Missing options are read as `{}`, so they are checked as `{}` too.
        z.strictObject({
            type: z.literal(viz.type),
            options: z.preprocess((options) => options ?? {}, viz.optionsSchema),
        })
    )
    return {
        type: 'chart',
        addMenuItems: [
            {
                label: 'Chart',
                // TODO(2026-11-23): Replace this hardcoded query with one the person picks when they add the tile.
                // The query is temporary. It gives the add menu a widget to insert before a query picker exists.
                create: () => ({
                    type: 'chart',
                    title: 'New chart',
                    config: {
                        query: { language: 'hogql', query: 'select count() from events' },
                        viz: { type: firstType },
                    },
                }),
            },
        ],
        size: UNKNOWN_WIDGET_SIZE,
        sizeFor: (widget) => vizTypes.find((viz) => viz.type === widget.config?.viz?.type)?.size ?? UNKNOWN_WIDGET_SIZE,
        configSchema: z
            .strictObject({
                query: widgetQuerySchema.optional(),
                targets: z.array(chartTargetSchema).min(1).max(MAX_CHART_TARGETS).optional(),
                viz: vizSchemas.length > 0 ? z.union(vizSchemas) : z.never(),
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
        refreshes: true,
    }
}
