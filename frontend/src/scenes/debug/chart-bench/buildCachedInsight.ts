import { NodeKind } from '~/queries/schema/schema-general'
import type { EventsNode, InsightVizNode, TrendsQuery } from '~/queries/schema/schema-general'
import type { QueryBasedInsightModel, TrendResult } from '~/types'
import { BaseMathType, ChartDisplayType, InsightType } from '~/types'

import type { BenchData } from './generateBenchData'

/**
 * Turns the harness's synthetic {labels, series[]} into the shape the real
 * PostHog trend chart expects:
 *
 *   - a `TrendsQuery` with one `EventsNode` per series (used by
 *     `trendsDataLogic` to drive display/interval/trendsFilter selectors).
 *   - a `cachedInsight` wrapping that query as an `InsightVizNode`, plus a
 *     `result` array of `TrendResult` carrying the actual numbers.
 *
 * We deliberately don't try to match real PostHog data — the goal is to feed
 * `trendsDataLogic` enough structure that the adapters (`ActionsLineGraph`,
 * `TrendsLineChart`) render without touching the backend.
 */
export interface BuiltInsight {
    query: InsightVizNode
    cachedInsight: Partial<QueryBasedInsightModel>
    cachedResults: { results: TrendResult[] }
}

interface BuildOptions {
    fillArea?: boolean
    /** Overrides the display type. When omitted, falls back to the line/area choice driven by `fillArea`. */
    display?: ChartDisplayType
}

export function buildCachedInsight(data: BenchData, options: BuildOptions = {}): BuiltInsight {
    const display =
        options.display ?? (options.fillArea ? ChartDisplayType.ActionsAreaGraph : ChartDisplayType.ActionsLineGraph)
    const trendsQuery: TrendsQuery = {
        kind: NodeKind.TrendsQuery,
        dateRange: {
            date_from: data.labels[0] ?? '-30d',
            date_to: data.labels[data.labels.length - 1] ?? null,
        },
        interval: 'day',
        series: data.series.map(
            (s, idx) =>
                // `order` isn't in the EventsNode schema but `trendsDataLogic` reads it off series entries.
                ({
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: s.label,
                    custom_name: s.label,
                    math: BaseMathType.TotalCount,
                    properties: [],
                    order: idx,
                }) as EventsNode
        ),
        trendsFilter: {
            display,
        },
    }

    const query: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: trendsQuery,
        full: false,
    }

    const trendResults: TrendResult[] = data.series.map((s, idx) => {
        const total = s.data.reduce((a, b) => a + b, 0)
        return {
            action: {
                id: s.key,
                type: 'events',
                order: idx,
                name: s.label,
                custom_name: s.label,
                math: 'total',
                math_property: null,
                math_group_type_index: null,
                properties: [],
            },
            label: s.label,
            count: total,
            data: s.data,
            // TrendResult's `labels` are human-readable (e.g. "4-Mar-2022") while
            // `days` are ISO — the chart uses `days` for x-axis positioning and
            // `labels` only for tooltip titles. We reuse the ISO strings for both.
            labels: s.data.map((_, i) => data.labels[i] ?? ''),
            days: data.labels.slice(),
            // Aggregated (horizontal `ActionsBarValue`) layouts drop series whose
            // aggregated_value is 0, so carry the series total here too.
            aggregated_value: total,
            filter: {
                insight: InsightType.TRENDS,
                interval: 'day',
                display,
            },
        }
    })

    const cachedInsight: Partial<QueryBasedInsightModel> = {
        id: 0,
        short_id: 'bench' as QueryBasedInsightModel['short_id'],
        name: 'chart bench',
        derived_name: 'chart bench',
        query,
        result: trendResults,
        dashboards: [],
    }

    return {
        query,
        cachedInsight,
        cachedResults: { results: trendResults },
    }
}
