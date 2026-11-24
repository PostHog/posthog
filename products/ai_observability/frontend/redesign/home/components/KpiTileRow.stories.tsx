import type { Meta, StoryObj } from '@storybook/react'

import { TraceMetricKeyApi } from '../../../generated/api.schemas'
import { METRICS, METRICS_NOT_SET_UP, TILE_LINKS } from '../homeFixtures'
import { KpiTileRow } from './KpiTileRow'

const meta: Meta<typeof KpiTileRow> = {
    title: 'Scenes-App/AI observability/Home/KPI tile row',
    component: KpiTileRow,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { metrics: METRICS, loading: false, links: TILE_LINKS, openChartKey: null, onToggleChart: () => {} },
}
export default meta

type Story = StoryObj<typeof KpiTileRow>

export const AllOk: Story = {}

export const ChartOpen: Story = { args: { openChartKey: TraceMetricKeyApi.ErrorRate } }

export const AllNotSetUp: Story = { args: { metrics: METRICS_NOT_SET_UP } }

export const Loading: Story = { args: { metrics: null, loading: true } }

export const NarrowContainer: Story = {
    decorators: [
        (StoryComponent) => (
            <div className="w-130">
                <StoryComponent />
            </div>
        ),
    ],
}

export const MediumContainer: Story = {
    decorators: [
        (StoryComponent) => (
            <div className="w-176">
                <StoryComponent />
            </div>
        ),
    ],
}
