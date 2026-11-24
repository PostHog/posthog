import type { Meta, StoryObj } from '@storybook/react'

import { KpiTileSparkline } from './KpiTileSparkline'

const meta: Meta<typeof KpiTileSparkline> = {
    title: 'Scenes-App/AI observability/Home/KPI tile sparkline',
    component: KpiTileSparkline,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { series: [120, 145, 170, 190, 230, 250, 290] },
    decorators: [
        (StoryComponent) => (
            <div className="h-8 w-48">
                <StoryComponent />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof KpiTileSparkline>

export const Trend: Story = {}

export const NarrowContainer: Story = {
    decorators: [
        (StoryComponent) => (
            <div className="h-8 w-20">
                <StoryComponent />
            </div>
        ),
    ],
}

export const WithGap: Story = { args: { series: [120, 145, null, null, 230, 250, 290] } }
