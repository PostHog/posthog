import { dashboard, hogql, insight, text, tile, type TileLayout } from '@posthog/sdk/define'

import { sortedOperations, sortedRegions, tags } from './config'
import { burnRate, duration, regression, successRate, volume } from './insights'
import { alertDeliveryByTypeQuery } from './queries'

function at(i: string, place: { x: number; y: number; w: number; h: number }, min = 2): { sm: TileLayout } {
    return { sm: { ...place, i, minH: min, minW: min, moved: false, static: false } }
}

// Success rate, volume, the explainer text and the regression table take rows 0 to 9.
const sectionsTop = 10

const sections = sortedOperations.flatMap((operation, index) => {
    const regions = sortedRegions(operation)
    const top = sectionsTop + index * (1 + regions.length * 3)
    const rows = regions.map((region, row) => ({
        region,
        slug: `${operation.key}_${region.toLowerCase()}`,
        y: top + 1 + row * 3,
    }))
    return [
        text(`## ${operation.name}`, { layouts: at(`header_${operation.key}`, { x: 0, y: top, w: 12, h: 1 }, 1) }),
        ...rows.map(({ region, slug, y }) =>
            tile(burnRate(operation, region), {
                key: `burn_${slug}`,
                layouts: at(`burn_${slug}`, { x: 0, y, w: 6, h: 3 }),
            })
        ),
        ...rows.map(({ region, slug, y }) =>
            tile(duration(operation, region), {
                key: `dur_${slug}`,
                layouts: at(`dur_${slug}`, { x: 6, y, w: 6, h: 3 }),
            })
        ),
    ]
})

export const sloMonitoring = dashboard('slo_monitoring', {
    name: 'SLO Monitoring',
    description:
        'Rolling success rates and burn rates for SLO-tracked operations. Uses slo_operation_completed events. Burn rate of 1.0 = consuming error budget at planned rate.',
    pinned: true,
    tags,
    tiles: [
        tile(successRate, { layouts: at('success_rate', { x: 0, y: 0, w: 8, h: 5 }) }),
        tile(volume, { layouts: at('volume', { x: 8, y: 0, w: 4, h: 5 }) }),
        tile(regression, { layouts: at('regression', { x: 0, y: 6, w: 12, h: 4 }) }),
        text(
            "**Success rate** is a 28-day rolling window showing the percentage of successful operations. **Burn rate** shows how fast you're consuming your error budget on a logarithmic scale — the Budget rate line marks sustainable consumption, crossing 100x burn indicates an active incident. **Duration** shows p50/p95/p99 operation latency in seconds.",
            { layouts: at('text', { x: 0, y: 5, w: 12, h: 1 }, 1) }
        ),
        ...sections,
    ],
})

// On the dashboard without a tile layout, so it is not one of the tiles above.
export const alertDeliveryByType = insight(
    'alert_delivery_by_type',
    hogql({
        name: 'SLO: Alert notification delivery by alert type',
        description: 'Daily delivery success for each alert type and region. New alert types appear automatically.',
        tags,
        dashboards: [sloMonitoring],
        query: alertDeliveryByTypeQuery,
        display: 'ActionsLineGraph',
        chartSettings: {
            xAxis: { column: 'day' },
            yAxis: [{ column: 'success_rate', settings: { formatting: { suffix: '%' } } }],
            seriesBreakdownColumn: 'series',
            showLegend: true,
        },
        tableSettings: {
            columns: [
                { column: 'day' },
                { column: 'series' },
                { column: 'success_rate', settings: { formatting: { suffix: '%' } } },
                { column: 'started' },
                { column: 'successes' },
                { column: 'failures' },
            ],
        },
    })
)
