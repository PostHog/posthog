import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../trace/storyFixtures'
import { TrendSparkline } from './TrendSparkline'

const meta: Meta<typeof TrendSparkline> = {
    title: 'Scenes-App/AI observability/Diagnostics/Trend sparkline',
    component: TrendSparkline,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { series: [12, 15, 9, 20, 22, 25, 31] },
    decorators: [withWidth(360)],
}
export default meta

type Story = StoryObj<typeof TrendSparkline>

export const Rising: Story = {}

export const Flat: Story = { args: { series: [0, 0, 0, 0, 0, 0, 0] } }

export const SingleBucket: Story = { args: { series: [42] } }
