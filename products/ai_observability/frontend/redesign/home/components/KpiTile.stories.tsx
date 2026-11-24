import type { Meta, StoryObj } from '@storybook/react'

import { TraceMetricKeyApi, type TraceMetricTileApi } from '../../../generated/api.schemas'
import { METRICS, METRICS_NOT_SET_UP } from '../homeFixtures'
import { KpiTile } from './KpiTile'

function tileOf(tiles: TraceMetricTileApi[], key: TraceMetricKeyApi): TraceMetricTileApi {
    const tile = tiles.find((candidate) => candidate.key === key)
    if (!tile) {
        throw new Error(`No ${key} tile in the fixture`)
    }
    return tile
}

const COST_TILE = tileOf(METRICS.tiles, TraceMetricKeyApi.Cost)

const meta: Meta<typeof KpiTile> = {
    title: 'Scenes-App/AI observability/Home/KPI tile',
    component: KpiTile,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { tile: COST_TILE },
    decorators: [
        (StoryComponent) => (
            <div className="w-56">
                <StoryComponent />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof KpiTile>

export const NeutralChange: Story = {}

export const GoodChange: Story = { args: { tile: tileOf(METRICS.tiles, TraceMetricKeyApi.P95Latency) } }

export const BadChange: Story = { args: { tile: tileOf(METRICS.tiles, TraceMetricKeyApi.ErrorRate) } }

export const LinkedToList: Story = { args: { to: '/ai-observability/traces' } }

export const NoPreviousPeriod: Story = { args: { tile: { ...COST_TILE, previous: null, change: null } } }

export const NoDataInRange: Story = {
    args: { tile: { ...COST_TILE, value: 0, previous: 0, change: null, series: [0, 0, 0, 0, 0, 0, 0] } },
}

export const NotSetUp: Story = { args: { tile: tileOf(METRICS_NOT_SET_UP.tiles, TraceMetricKeyApi.Sessions) } }

export const Loading: Story = { args: { tile: null } }
