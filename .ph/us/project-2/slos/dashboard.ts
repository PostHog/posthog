import {
    dashboard,
    insight,
    type InsightDefinition,
    type InsightInput,
    text,
    type TileLayout,
} from '@posthog/sdk/define'

import { tags } from '../shared/teams'
import { burnRate, type SloRegion, sloRegions, successRates } from './insights'

function at(i: string, place: { x: number; y: number; w: number; h: number }): { sm: TileLayout } {
    return { sm: { ...place, i, minH: 1, minW: 1, moved: false, static: false } }
}

const sloInsight = (region: SloRegion, extra: Pick<InsightInput, 'dashboards'> = {}): InsightDefinition =>
    insight(`slo-${region.key}`, { ...burnRate(region), ...extra })

const regionByKey = new Map(sloRegions.map((region) => [region.key, region]))
const regionOf = (key: string): SloRegion => regionByKey.get(key) as SloRegion

// The tiles' layout ids are the dashboard's own, from when the tiles were placed in the UI.
const burnRateTiles: [string, string, { x: number; y: number }][] = [
    ['alerts_us', '6372084', { x: 0, y: 6 }],
    ['alerts_timeliness_us', '6371880', { x: 6, y: 6 }],
    ['exports_us', '6371881', { x: 0, y: 11 }],
    ['exports_eu', '6371877', { x: 6, y: 11 }],
    ['cohorts_us', '6371878', { x: 0, y: 16 }],
    ['cohorts_eu', '6371879', { x: 6, y: 16 }],
    ['subscriptions_us', 'subscriptions_us', { x: 0, y: 21 }],
    ['subscriptions_eu', 'subscriptions_eu', { x: 6, y: 21 }],
]

export const sloSuccessRates = insight('slo_success_rates', successRates)
export const tiledBurnRates = burnRateTiles.map(([key]) => sloInsight(regionOf(key)))

export const slosDashboard = dashboard('team_analytics_platform_slos', {
    name: '[team-analytics-platform] SLOs',
    pinned: true,
    tags: [tags.managed],
    tiles: [
        { insight: sloSuccessRates, layouts: at('0', { x: 0, y: 0, w: 12, h: 5 }) },
        text(
            "**Success rate** is a 30-day rolling window showing the percentage of successful operations per SLO. **Burn rate** (below) measures how fast you're consuming your error budget — 1.0 means you're spending at exactly the sustainable rate, >1.0 means you'll exhaust it before the window ends.",
            { layouts: at('1', { x: 0, y: 5, w: 12, h: 1 }) }
        ),
        ...burnRateTiles.map(([, i, place], index) => ({
            insight: tiledBurnRates[index] as InsightDefinition,
            layouts: at(i, { ...place, w: 6, h: 5 }),
        })),
    ],
})

// On the dashboard without a tile layout.
const tiled = new Set(burnRateTiles.map(([key]) => key))
export const untiledBurnRates = sloRegions
    .filter((region) => !tiled.has(region.key))
    .map((region) => sloInsight(region, { dashboards: [slosDashboard] }))
