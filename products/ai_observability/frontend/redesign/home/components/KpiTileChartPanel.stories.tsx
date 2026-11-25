import type { Meta, StoryObj } from '@storybook/react'

import { TraceMetricBucketSizeApi, TraceMetricKeyApi, type TraceMetricTileApi } from '../../../generated/api.schemas'
import { METRICS, TILE_LINKS } from '../homeFixtures'
import { KpiTileChartPanel } from './KpiTileChartPanel'

function tileOf(key: TraceMetricKeyApi): TraceMetricTileApi {
    const tile = METRICS.tiles.find((candidate) => candidate.key === key)
    if (!tile) {
        throw new Error(`No ${key} tile in the fixture`)
    }
    return tile
}

const HOURS = Array.from({ length: 24 }, (_, hour) => `2026-11-18T${String(hour).padStart(2, '0')}:00:00Z`)

const meta: Meta<typeof KpiTileChartPanel> = {
    title: 'Scenes-App/AI observability/Home/KPI tile chart panel',
    component: KpiTileChartPanel,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        tile: tileOf(TraceMetricKeyApi.ErrorRate),
        bucketStarts: METRICS.bucketStarts,
        bucketSize: METRICS.bucketSize,
        dateFrom: '-7d',
        dateTo: null,
        timezone: 'UTC',
        activityUrl: TILE_LINKS[TraceMetricKeyApi.ErrorRate],
        insightUrl: '/sql',
        onClose: () => {},
    },
    decorators: [
        (StoryComponent) => (
            <div className="w-240">
                <StoryComponent />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof KpiTileChartPanel>

export const WithActivityLink: Story = {}

export const HourlyWithGapsAndNoActivityLink: Story = {
    args: {
        tile: {
            ...tileOf(TraceMetricKeyApi.P95Latency),
            series: HOURS.map((_, hour) => (hour >= 2 && hour < 6 ? null : 2 + Math.sin(hour / 3) + hour / 10)),
        },
        bucketStarts: HOURS,
        bucketSize: TraceMetricBucketSizeApi.Hour,
        dateFrom: '-24h',
        activityUrl: undefined,
    },
}

export const NarrowContainer: Story = {
    args: { tile: tileOf(TraceMetricKeyApi.Cost), activityUrl: undefined },
    decorators: [
        (StoryComponent) => (
            <div className="w-96">
                <StoryComponent />
            </div>
        ),
    ],
}
